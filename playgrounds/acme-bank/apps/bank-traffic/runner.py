"""The loop: wait for the platform, warm it up with a burst, then one scenario every couple of minutes.

Nothing a scenario does can end it. A scenario that fails, raises or hangs is counted and logged like any other and
the loop goes on; a platform that stops answering is waited for again, feature by feature, and the traffic that
does not need it continues.
"""
import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from checks import FAILED, INCONCLUSIVE, OK, SKIPPED, Result
from readiness import Readiness, describe
from scenarios import Scenario, World
from wire import PlatformError

log = logging.getLogger("bank-traffic")
STATUSES = (OK, FAILED, INCONCLUSIVE, SKIPPED)


@dataclass(frozen=True)
class Pace:
    warmup_calls: int = 40            # a burst of calls once the platform is ready, so the dashboards have data
    warmup_seconds: float = 180
    interval: float = 120             # seconds between two scenarios at rate 1: 30 an hour
    jitter: float = 0.25              # of the interval, either way, so the calls do not tick like a clock
    timeout: float = 150              # seconds a scenario may take: Ace answers within 30 s, a chat holds several calls
    first_wait: float = 5             # while the platform is not ready: asked again after this, then twice as long
    longest_wait: float = 60
    trouble: int = 3                  # scenarios in a row that meet an unavailable platform before it is waited for


class Counters:
    """What each scenario did since the start, or the last reset."""

    def __init__(self) -> None:
        self.scenarios: dict[str, dict[str, Any]] = {}

    def record(self, name: str, result: Result, ms: int) -> None:
        entry = self.scenarios.setdefault(name, {"runs": 0, **{status: 0 for status in STATUSES}})
        entry["runs"] += 1
        entry[result.status] += 1
        entry["last"] = {"outcome": result.status, "ms": ms, "tokens": result.tokens, "detail": result.detail,
                         "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def totals(self) -> dict[str, int]:
        return {"runs": sum(e["runs"] for e in self.scenarios.values()),
                **{status: sum(e[status] for e in self.scenarios.values()) for status in STATUSES}}


class Runner:
    def __init__(self, world: World, scenarios: tuple[Scenario, ...], readiness: Readiness, rate: float = 1.0,
                 enabled: bool = True, pace: Pace = Pace(), clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.world, self.scenarios, self.readiness, self.rate, self.pace = world, scenarios, readiness, rate, pace
        self._clock, self._sleep = clock, sleep
        self._running = asyncio.Event()
        if enabled:
            self._running.set()
        self.counters = Counters()
        self.phase = "waiting"             # waiting for the platform, warming-up, running
        self.current: str | None = None
        self.warmup_done = 0
        self._trouble: dict[str, int] = {}
        self._next_look = 0.0
        self._started_at = datetime.now(timezone.utc)

    # --- The control port ---------------------------------------------------------------------------------------

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    def pause(self) -> None:
        """No new scenario starts; the one in progress ends, so no transfer is left half done."""
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def reset(self) -> None:
        """What "Start the bank over" asks of the generator: the counters start again and no transfer is owed (the bank is
        reset with them). The ledger stays: the gateway's windows go on counting what was spent."""
        self.counters = Counters()
        self.world.transfers.reset()

    def status(self) -> dict[str, Any]:
        return {"state": "paused" if self.paused else self.phase, "phase": self.phase, "paused": self.paused,
                "in_progress": self.current, "rate": self.rate,
                "started_at": self._started_at.isoformat(timespec="seconds"), "waiting_for": self.readiness.waiting,
                "warmup": {"done": self.warmup_done, "of": self.pace.warmup_calls},
                "totals": self.counters.totals(), "scenarios": self.counters.scenarios,
                "ledger": self.world.ledger.snapshot(), "transfers": self.world.transfers.status()}

    # --- The loop -----------------------------------------------------------------------------------------------

    async def run(self) -> None:
        await self._wait_for_platform()
        await self._warm_up()
        self.phase = "running"
        while True:
            await self._running.wait()
            await self._look_again()
            scenario = self._pick()
            if scenario is None:
                await self._sleep(self.pace.first_wait)      # nothing can run now: look again soon
                continue
            await self._settled_run(scenario)
            await self._sleep(self._gap())

    async def _wait_for_platform(self) -> None:
        """Until every feature is ready. Asking again costs a few free requests, so the waits grow to a minute."""
        wait = self.pace.first_wait
        while True:
            await self._running.wait()
            await self.readiness.check()
            if not self.readiness.waiting:
                log.info("the platform is ready")
                return
            log.info("waiting for the platform: %s", describe(self.readiness.waiting))
            await self._sleep(wait)
            wait = min(wait * 2, self.pace.longest_wait)

    async def _look_again(self) -> None:
        """What a scenario found down is asked again now and then, so its traffic comes back by itself."""
        if self.readiness.waiting and self._clock() >= self._next_look:
            self._next_look = self._clock() + self.pace.longest_wait
            await self.readiness.check()

    async def _warm_up(self) -> None:
        """A first pass over every scenario, in a random order so the chats and the calls alternate, then picks
        from the table, over `warmup_seconds` in all."""
        self.phase = "warming-up"
        log.info("warming up: %d calls over %d s", self.pace.warmup_calls, self.pace.warmup_seconds)
        first_pass = list(self.scenarios)
        self.world.rng.shuffle(first_pass)
        gap = self.pace.warmup_seconds / self.pace.warmup_calls if self.pace.warmup_calls else 0
        for index in range(self.pace.warmup_calls):
            await self._running.wait()
            await self._look_again()
            started = self._clock()
            scenario = first_pass[index] if index < len(first_pass) else self._pick()
            if scenario is not None and self._allowed(scenario):
                await self._settled_run(scenario)
            self.warmup_done = index + 1
            await self._sleep(max(gap - (self._clock() - started), 0))
        log.info("warm-up done: one scenario about every %d s", self.pace.interval / self.rate)

    def _gap(self) -> float:
        spread = self.world.rng.uniform(-self.pace.jitter, self.pace.jitter)
        return self.pace.interval / self.rate * (1 + spread)

    def _allowed(self, scenario: Scenario) -> bool:
        owed = bool(self.world.transfers.owed)
        return scenario.needs <= self.readiness.ready and not (scenario.moves_money and owed)

    def _pick(self) -> Scenario | None:
        candidates = [scenario for scenario in self.scenarios if self._allowed(scenario)]
        if not candidates:
            return None
        return self.world.rng.choices(candidates, weights=[scenario.weight for scenario in candidates])[0]

    # --- One scenario -------------------------------------------------------------------------------------------

    async def _settled_run(self, scenario: Scenario) -> None:
        """The scenario, then whatever it owes: the money it moved goes back before anything else happens."""
        await self.run_one(scenario)
        try:
            await self.world.transfers.settle()
        except Exception:
            log.exception("giving a transfer back failed")

    async def run_one(self, scenario: Scenario) -> Result:
        refusal = self.world.ledger.refusal(scenario.estimate)
        started = self._clock()
        if refusal:
            result = Result(SKIPPED, refusal)
        else:
            result = await self._attempt(scenario)
            for limit, amount in result.charges.items():
                self.world.ledger.charge(limit, amount)
        ms = int((self._clock() - started) * 1000)
        self.counters.record(scenario.name, result, ms)
        self._log(scenario.name, result, ms)
        return result

    async def _attempt(self, scenario: Scenario) -> Result:
        self.current = scenario.name
        # what a scenario that may move money leaves behind is found in the balances if it ends without an answer
        watched = self.world.transfers.watch() if scenario.moves_money else contextlib.nullcontext()
        try:
            async with watched:
                result = await asyncio.wait_for(scenario.run(self.world), self.pace.timeout)
        except (PlatformError, TimeoutError) as e:      # the platform did not answer: not a failed expectation
            result = Result(FAILED, str(e) or "no answer in time")
            self._note_trouble(scenario, e)
        except Exception as e:      # a scenario never ends the loop, and a bug in one is worth a traceback
            log.exception("scenario %s raised", scenario.name)
            result = Result(FAILED, f"{type(e).__name__}: {e}")
        else:
            self._trouble[scenario.name] = 0
        finally:
            self.current = None
        return result

    def _note_trouble(self, scenario: Scenario, error: Exception) -> None:
        """After a few scenarios in a row that met a platform not answering, the features the scenario needs are
        waited for again instead of being asked for more."""
        self._trouble[scenario.name] = self._trouble.get(scenario.name, 0) + 1
        if self._trouble[scenario.name] >= self.pace.trouble:
            self._trouble[scenario.name] = 0
            for feature in scenario.needs:
                self.readiness.mark_down(feature, str(error) or "no answer in time")
            self._next_look = self._clock() + self.pace.longest_wait

    @staticmethod
    def _log(name: str, result: Result, ms: int) -> None:
        line = f"scenario={name} outcome={result.status} ms={ms} tokens={result.tokens}"
        if result.detail:
            line += f" detail={result.detail}"
        log.log(logging.WARNING if result.status == FAILED else logging.INFO, line)
