"""The loop: waiting for the platform, the warm-up, the trickle, pause and resume, and a platform or a scenario that
misbehaves. The scenarios here are small stand-ins, so the loop is tested alone and on a clock the tests move."""
import asyncio
import contextlib
import random
import unittest

from checks import FAILED, OK, SKIPPED, Result
from ledger import Ledger
from readiness import Readiness
from runner import Pace, Runner
from scenarios import Scenario, World
from tests.fakes import Clock
from wire import PlatformError

FAST = Pace(warmup_calls=4, warmup_seconds=8, interval=100, jitter=0, timeout=5, first_wait=5, longest_wait=60,
            trouble=3)


class NoMoney:
    owed: list = []

    def __init__(self):
        self.watched = 0

    @contextlib.asynccontextmanager
    async def watch(self):
        self.watched += 1
        yield

    async def settle(self): ...
    def reset(self): self.owed.clear()
    def status(self): return {"owed": self.owed}


class Rig:
    """A runner with stand-in scenarios, a readiness whose answers the test scripts, and a clock it moves."""

    def __init__(self, scenarios, probes=None, pace=FAST, rate=1.0, enabled=True):
        self.clock = Clock()
        self.ledger = Ledger(clock=self.clock)
        self.world = World(None, None, None, None, self.ledger, NoMoney(), random.Random(5))
        self.readiness = Readiness(probes if probes is not None else {"llm": self.ok, "mcp": self.ok})
        self.runner = Runner(self.world, scenarios, self.readiness, rate, enabled, pace, self.clock, self.clock.sleep)
        self.task = None

    @staticmethod
    async def ok():
        return None

    def start(self):
        self.task = asyncio.create_task(self.runner.run())
        return self

    async def until(self, condition, turns=5000):
        for _ in range(turns):
            if condition():
                return
            await asyncio.sleep(0)
        raise AssertionError("it did not happen")

    async def stop(self):
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.task


def scenario(name, ran, needs=("llm",), weight=1, estimate=None, outcome=OK, money=False):
    async def run(world):
        ran.append(name)
        return outcome if isinstance(outcome, Result) else Result(outcome)
    return Scenario(name, weight, frozenset(needs), run, estimate or {}, money)


class Waiting(unittest.IsolatedAsyncioTestCase):
    async def test_it_waits_for_the_platform_and_says_what_it_waits_for(self):
        ran = []
        answers = iter(["the LLM proxy answered HTTP 404 to the Traffic key", "the LLM proxy answered HTTP 503", None])

        async def llm():
            reason = next(answers)
            if reason:
                raise PlatformError(reason)
        rig = Rig([scenario("a", ran)], {"llm": llm, "mcp": Rig.ok})
        with self.assertLogs("bank-traffic", "INFO") as logs:
            rig.start()
            await rig.until(lambda: rig.runner.phase != "waiting")
            await rig.stop()
        self.assertEqual(logs.output[:3], [
            "INFO:bank-traffic:waiting for the platform: llm: the LLM proxy answered HTTP 404 to the Traffic key",
            "INFO:bank-traffic:waiting for the platform: llm: the LLM proxy answered HTTP 503",
            "INFO:bank-traffic:the platform is ready"])
        self.assertEqual(rig.clock.slept[:2], [5, 10])

    async def test_the_waits_grow_to_a_minute_and_stay_there(self):
        async def never():
            raise PlatformError("not yet")
        rig = Rig([scenario("a", [])], {"llm": never}).start()
        await rig.until(lambda: len(rig.clock.slept) >= 8)
        await rig.stop()
        self.assertEqual(rig.clock.slept[:8], [5, 10, 20, 40, 60, 60, 60, 60])
        self.assertEqual(rig.runner.status()["state"], "waiting")
        self.assertEqual(rig.runner.status()["waiting_for"], {"llm": "not yet"})

    async def test_nothing_runs_before_the_platform_is_ready(self):
        ran = []

        async def never():
            raise PlatformError("not yet")
        rig = Rig([scenario("a", ran)], {"llm": never}).start()
        await rig.until(lambda: len(rig.clock.slept) >= 3)
        await rig.stop()
        self.assertEqual(ran, [])


class WarmUpAndTrickle(unittest.IsolatedAsyncioTestCase):
    async def test_the_warm_up_runs_every_scenario_once_then_draws_from_the_table(self):
        ran = []
        rig = Rig([scenario(name, ran) for name in "abc"]).start()
        await rig.until(lambda: rig.runner.warmup_done == 4)
        self.assertEqual(sorted(ran[:3]), ["a", "b", "c"])
        self.assertEqual(len(ran), 4)
        self.assertEqual(rig.runner.status()["state"], "warming-up")
        await rig.stop()

    async def test_the_warm_up_is_spread_over_its_time(self):
        rig = Rig([scenario("a", [])]).start()
        await rig.until(lambda: rig.runner.phase == "running")
        await rig.stop()
        self.assertEqual(rig.clock.slept[:4], [2.0, 2.0, 2.0, 2.0])      # 8 seconds over 4 calls

    async def test_then_one_scenario_every_two_minutes_at_rate_one(self):
        ran = []
        rig = Rig([scenario("a", ran)], pace=Pace(**{**FAST.__dict__, "interval": 120})).start()
        await rig.until(lambda: len(ran) >= 7)
        await rig.stop()
        self.assertEqual(set(rig.clock.slept[-3:]), {120.0})
        self.assertEqual(rig.runner.status()["state"], "running")

    async def test_the_rate_scales_the_pace(self):
        ran = []
        rig = Rig([scenario("a", ran)], rate=4.0, pace=Pace(**{**FAST.__dict__, "interval": 120})).start()
        await rig.until(lambda: len(ran) >= 7)
        await rig.stop()
        self.assertEqual(set(rig.clock.slept[-3:]), {30.0})

    async def test_the_calls_do_not_tick_like_a_clock(self):
        ran = []
        rig = Rig([scenario("a", ran)], pace=Pace(**{**FAST.__dict__, "interval": 120, "jitter": 0.25})).start()
        await rig.until(lambda: len(ran) >= 14)
        await rig.stop()
        gaps = rig.clock.slept[-8:]
        self.assertGreater(len(set(gaps)), 3)
        self.assertTrue(all(90 <= gap <= 150 for gap in gaps))

    async def test_the_draw_follows_the_weights(self):
        ran = []
        rig = Rig([scenario("often", ran, weight=9), scenario("rarely", ran, weight=1)],
                  pace=Pace(**{**FAST.__dict__, "warmup_calls": 0})).start()
        await rig.until(lambda: len(ran) >= 200)
        await rig.stop()
        self.assertGreater(ran.count("often"), 5 * ran.count("rarely"))


class PauseAndResume(unittest.IsolatedAsyncioTestCase):
    async def test_traffic_off_starts_paused_and_resume_starts_it(self):
        ran = []
        rig = Rig([scenario("a", ran)], enabled=False).start()
        for _ in range(200):
            await asyncio.sleep(0)
        self.assertEqual((ran, rig.runner.status()["state"], rig.runner.paused), ([], "paused", True))
        self.assertEqual(rig.readiness.waiting, {"llm": "not checked yet", "mcp": "not checked yet"})   # not even asked
        rig.runner.resume()
        await rig.until(lambda: len(ran) >= 1)
        self.assertEqual(rig.runner.paused, False)
        await rig.stop()

    async def test_pause_stops_new_scenarios_and_resume_goes_on(self):
        ran = []
        rig = Rig([scenario("a", ran)]).start()
        await rig.until(lambda: len(ran) >= 6)
        rig.runner.pause()
        for _ in range(50):
            await asyncio.sleep(0)
        stopped_at = len(ran)
        for _ in range(500):
            await asyncio.sleep(0)
        self.assertEqual(len(ran), stopped_at)
        self.assertEqual(rig.runner.status()["state"], "paused")
        rig.runner.resume()
        await rig.until(lambda: len(ran) > stopped_at)
        await rig.stop()

    async def test_the_scenario_in_progress_is_finished_not_cut(self):
        started, release, done = asyncio.Event(), asyncio.Event(), []

        async def slow(world):
            started.set()
            await release.wait()
            done.append("slow")
            return Result(OK)
        rig = Rig([Scenario("slow", 1, frozenset({"llm"}), slow)],
                  pace=Pace(**{**FAST.__dict__, "warmup_calls": 0})).start()
        await started.wait()
        rig.runner.pause()
        self.assertEqual(rig.runner.status()["in_progress"], "slow")
        release.set()
        await rig.until(lambda: done)
        await rig.until(lambda: rig.runner.counters.totals()["runs"] == 1)
        self.assertIsNone(rig.runner.status()["in_progress"])
        await rig.stop()

    async def test_reset_starts_the_counters_again_and_forgets_what_was_owed(self):
        ran = []
        rig = Rig([scenario("a", ran)]).start()
        await rig.until(lambda: len(ran) >= 3)
        rig.world.transfers.owed.append("120 EUR")
        rig.runner.reset()
        self.assertEqual(rig.runner.counters.totals(), {"runs": 0, OK: 0, FAILED: 0, "inconclusive": 0, SKIPPED: 0})
        self.assertEqual(rig.world.transfers.owed, [])
        await rig.stop()


class Isolation(unittest.IsolatedAsyncioTestCase):
    async def test_a_scenario_that_raises_is_counted_and_the_others_go_on(self):
        ran = []

        async def bug(world):
            raise ValueError("a bug in a scenario")
        rig = Rig([Scenario("bug", 1, frozenset({"llm"}), bug), scenario("fine", ran)],
                  pace=Pace(**{**FAST.__dict__, "warmup_calls": 6}))
        with self.assertLogs("bank-traffic", "WARNING") as logs:
            rig.start()
            await rig.until(lambda: len(ran) >= 5)
            await rig.stop()
        counters = rig.runner.counters.scenarios
        self.assertGreaterEqual(counters["bug"][FAILED], 1)
        self.assertEqual(counters["bug"]["last"]["detail"], "ValueError: a bug in a scenario")
        self.assertTrue(any("scenario bug raised" in line for line in logs.output))
        self.assertIn(counters["bug"]["runs"], range(1, 20))

    async def test_a_scenario_that_never_answers_is_cut_and_the_loop_goes_on(self):
        ran = []

        async def hang(world):
            await asyncio.sleep(3600)
        rig = Rig([Scenario("hang", 1, frozenset({"llm"}), hang), scenario("fine", ran)],
                  pace=Pace(**{**FAST.__dict__, "timeout": 0.01, "warmup_calls": 4}))
        rig.start()
        await rig.until(lambda: len(ran) >= 3, turns=100000)
        await rig.stop()
        last = rig.runner.counters.scenarios["hang"]["last"]
        self.assertEqual((last["outcome"], last["detail"]), (FAILED, "no answer in time"))

    async def test_a_platform_that_does_not_answer_three_times_in_a_row_is_waited_for_again(self):
        ran, up = [], {"on": True}

        async def probe():
            if not up["on"]:
                raise PlatformError("the AI workspace does not exist yet")

        async def workspace(world):
            if not up["on"]:
                raise PlatformError("HTTP 404: No context-path matches the request URI.")
            return Result(OK)
        rig = Rig([Scenario("workspace", 1, frozenset({"workspace"}), workspace), scenario("fine", ran)],
                  {"llm": Rig.ok, "workspace": probe}, pace=Pace(**{**FAST.__dict__, "warmup_calls": 0})).start()
        counters = rig.runner.counters.scenarios
        await rig.until(lambda: counters.get("workspace", {}).get(OK, 0) >= 2)
        up["on"] = False
        await rig.until(lambda: "workspace" in rig.readiness.waiting)
        self.assertEqual(counters["workspace"][FAILED], 3)                       # three, then it is waited for
        frozen, others = counters["workspace"]["runs"], len(ran)
        await rig.until(lambda: len(ran) >= others + 10)                         # the other traffic goes on
        self.assertEqual(counters["workspace"]["runs"], frozen)                  # and this one is not tried
        up["on"] = True
        await rig.until(lambda: counters["workspace"]["runs"] > frozen)          # until the probe says it is back
        self.assertEqual(rig.readiness.waiting, {})
        await rig.stop()

    async def test_when_everything_is_down_nothing_runs_and_it_asks_again_every_minute_at_most(self):
        ran, asked, up = [], [], {"on": True}

        async def probe():
            asked.append(rig.clock.now)
            if not up["on"]:
                raise PlatformError("still down")

        async def scenario_run(world):
            if not up["on"]:
                raise PlatformError("HTTP 503")
            ran.append(1)
            return Result(OK)
        rig = Rig([Scenario("w", 1, frozenset({"llm"}), scenario_run)], {"llm": probe},
                  pace=Pace(**{**FAST.__dict__, "warmup_calls": 0})).start()
        await rig.until(lambda: len(ran) >= 2)
        up["on"] = False
        await rig.until(lambda: "llm" in rig.readiness.waiting)
        asked.clear()
        await rig.until(lambda: len(asked) >= 3, turns=100000)
        self.assertTrue(all(b - a >= 60 for a, b in zip(asked, asked[1:])), asked)
        self.assertGreaterEqual(rig.clock.slept.count(5), 10)                    # idle, looking again soon
        runs = len(ran)
        up["on"] = True
        await rig.until(lambda: len(ran) > runs, turns=100000)
        await rig.stop()


class Budgets(unittest.IsolatedAsyncioTestCase):
    async def test_a_scenario_over_its_share_is_skipped_not_run(self):
        ran = []
        rig = Rig([scenario("big", ran, estimate={"ace": 400_001}), scenario("fine", ran)],
                  pace=Pace(**{**FAST.__dict__, "warmup_calls": 6}))
        with self.assertLogs("bank-traffic", "INFO") as logs:
            rig.start()
            await rig.until(lambda: rig.runner.warmup_done == 6)
            await rig.stop()
        self.assertNotIn("big", ran)
        self.assertGreaterEqual(rig.runner.counters.scenarios["big"][SKIPPED], 1)
        self.assertTrue(any("scenario=big outcome=skipped" in line and "ace: 0% of 1,000,000 tokens an hour" in line
                            for line in logs.output))

    async def test_what_a_scenario_spent_is_charged_and_closes_the_door_at_the_share(self):
        ran = []
        spend = Result(OK, tokens=300_000, charges={"ace": 300_000})
        rig = Rig([scenario("chat", ran, estimate={"ace": 100_000}, outcome=spend)],
                  pace=Pace(**{**FAST.__dict__, "warmup_calls": 3})).start()
        await rig.until(lambda: rig.runner.warmup_done == 3)
        await rig.stop()
        self.assertEqual(len(ran), 2)                         # 300,000 spent, 100,000 more is the 400,000 share
        self.assertEqual(rig.ledger.used("ace"), 600_000)               # the scenario spent more than it announced
        self.assertEqual(rig.runner.counters.scenarios["chat"][SKIPPED], 1)    # and the third is over the share

    async def test_a_scenario_that_moves_money_does_not_start_while_a_transfer_is_owed(self):
        ran = []
        rig = Rig([scenario("send", ran, money=True), scenario("read", ran)],
                  pace=Pace(**{**FAST.__dict__, "warmup_calls": 0}))
        rig.world.transfers.owed = ["120 EUR"]
        rig.start()
        await rig.until(lambda: len(ran) >= 6)
        await rig.stop()
        self.assertEqual(set(ran), {"read"})


class Money(unittest.IsolatedAsyncioTestCase):
    async def test_only_a_scenario_that_may_move_money_is_watched(self):
        rig = Rig([scenario("send", [], money=True), scenario("read", [])])
        await rig.runner.run_one(rig.runner.scenarios[1])
        self.assertEqual(rig.world.transfers.watched, 0)
        await rig.runner.run_one(rig.runner.scenarios[0])
        self.assertEqual(rig.world.transfers.watched, 1)


class Reporting(unittest.IsolatedAsyncioTestCase):
    async def test_one_line_per_scenario_with_its_outcome_time_and_tokens(self):
        ran = []
        rig = Rig([scenario("a", ran, outcome=Result(OK, tokens=1534))],
                  pace=Pace(**{**FAST.__dict__, "warmup_calls": 1}))
        with self.assertLogs("bank-traffic", "INFO") as logs:
            rig.start()
            await rig.until(lambda: len(ran) >= 1)
            await rig.until(lambda: rig.runner.counters.totals()["runs"] == 1)
            await rig.stop()
        lines = [line for line in logs.output if "scenario=" in line]
        self.assertEqual(lines[0], "INFO:bank-traffic:scenario=a outcome=ok ms=0 tokens=1534")

    async def test_a_failure_is_a_warning_with_the_reason(self):
        rig = Rig([scenario("a", [], outcome=Result(FAILED, "list_accounts came back ok, expected it denied"))])
        with self.assertLogs("bank-traffic", "WARNING") as logs:
            await rig.runner.run_one(rig.runner.scenarios[0])
        self.assertEqual(logs.output, ["WARNING:bank-traffic:scenario=a outcome=failed ms=0 tokens=0 "
                                       "detail=list_accounts came back ok, expected it denied"])

    async def test_the_status_holds_the_counters_the_ledger_and_the_state(self):
        ran = []
        rig = Rig([scenario("a", ran), scenario("b", ran, outcome=FAILED)])
        await rig.runner.run_one(rig.runner.scenarios[0])
        await rig.runner.run_one(rig.runner.scenarios[1])
        status = rig.runner.status()
        self.assertEqual(status["totals"], {"runs": 2, OK: 1, FAILED: 1, "inconclusive": 0, SKIPPED: 0})
        self.assertEqual(status["scenarios"]["a"]["runs"], 1)
        self.assertEqual(status["scenarios"]["b"]["last"]["outcome"], FAILED)
        self.assertEqual(set(status["ledger"]), {"ace", "traffic", "team-care", "team-fraud"})
        self.assertEqual((status["state"], status["rate"], status["warmup"]), ("waiting", 1.0, {"done": 0, "of": 4}))
        self.assertEqual(status["transfers"], {"owed": []})


if __name__ == "__main__":
    unittest.main()
