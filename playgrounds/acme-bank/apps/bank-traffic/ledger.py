"""Budget arithmetic: how much of each limit the traffic may use.

The traffic shares the gateway with a person giving a demo, so it never takes more than SHARE of any limit: a
scenario that would go over is skipped, and tried again when what it spent has left the window. The ledger adds up
what was spent in the last `window` seconds. The gateway's limits are set to roll (`resetStrategy: ROLLING`) but may
refill in one step, an hour after the first call. A sum over the last window is never lower than what such a window
holds, so the ledger errs on the side of spending less.

The ledger counts what the traffic spends itself. Where the gateway says how much is left (the rate-limit headers
of an answer), that number is a floor: somebody else may have spent from the same budget.
"""
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import Callable

MINUTE, HOUR, DAY = 60, 3600, 86400
SHARE = 0.4          # of a limit: below the 50% at which a workspace budget moves its users to the small model
WINDOW_NAMES = {MINUTE: "a minute", HOUR: "an hour", DAY: "a day"}


@dataclass(frozen=True)
class Limit:
    name: str
    amount: float        # tokens, or US dollars
    window: int          # seconds
    unit: str            # "tokens" or "USD"


# The limits the seed sets: the plans Ace agent and Traffic of seed/apim/apis/acme-bank-llm.json, the budgets Customer
# care and Fraud analytics of seed/aim/workspaces/acme-bank-teams.yaml. The headers of the first answer correct them if
# the seed changes
DEMO_LIMITS = (
    Limit("ace", 1_000_000, HOUR, "tokens"),       # plan Ace agent: every chat of the bank's agent, anyone's
    Limit("traffic", 3_000, MINUTE, "tokens"),     # plan Traffic: the generator's own key
    Limit("team-care", 5.00, DAY, "USD"),          # budget Customer care
    Limit("team-fraud", 2.00, DAY, "USD"),         # budget Fraud analytics
)

# USD per million tokens, input and output, as the seed prices the models (seed/aim/models/qwen3-1-7b.yaml for smart,
# seed/aim/models/qwen3-0-6b.yaml for lite): inflated so that a few dollars of budget move
PRICES = {"smart": (50, 50), "lite": (20, 20)}
LITE_NAMES = ("lite", "0.6b")


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """What an answer costs in a workspace. An unknown model is priced as the dearer one, so a guess errs on the
    side of spending less."""
    lite = any(name in model for name in LITE_NAMES)
    price_in, price_out = PRICES["lite" if lite else "smart"]
    return (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000


def describe(limit: Limit) -> str:
    amount = f"{limit.amount:,.0f} tokens" if limit.unit == "tokens" else f"{limit.amount:.2f} USD"
    return f"{amount} {WINDOW_NAMES[limit.window]}"


class Ledger:
    def __init__(self, limits: tuple[Limit, ...] = DEMO_LIMITS, share: float = SHARE,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.share, self._clock = share, clock
        self._limits = {limit.name: limit for limit in limits}
        self._spent = {name: deque() for name in self._limits}          # (when, amount), oldest first
        self._seen: dict[str, tuple[float, float]] = {}                 # what the gateway counted, until when
        self._blocked: dict[str, float] = {}                            # until when the gateway refuses

    def used(self, name: str) -> float:
        now, window = self._clock(), self._limits[name].window
        spent = self._spent[name]
        while spent and spent[0][0] <= now - window:
            spent.popleft()
        seen, until = self._seen.get(name, (0.0, 0.0))
        return max(sum(amount for _, amount in spent), seen if now < until else 0.0)

    def charge(self, name: str, amount: float) -> None:
        if amount > 0:
            self._spent[name].append((self._clock(), amount))

    def refusal(self, charges: dict[str, float]) -> str | None:
        """Why the traffic may not spend `charges` now, or None when it may."""
        for name, amount in charges.items():
            limit = self._limits[name]
            if self._blocked.get(name, 0.0) > self._clock():
                return f"{name}: the gateway refuses it for now"
            used = self.used(name)
            if used + amount > self.share * limit.amount:
                return (f"{name}: {used / limit.amount:.0%} of {describe(limit)} used, "
                        f"the traffic keeps to {self.share:.0%}")
        return None

    def observe(self, name: str, limit: float | None, remaining: float | None, seconds_left: float | None) -> None:
        """The gateway's own count, from the rate-limit headers of an answer: the limit it applies, and what is left
        of it for `seconds_left` (the window when it does not say)."""
        if limit:
            self._limits[name] = replace(self._limits[name], amount=limit)
        if limit and remaining is not None:
            window = self._limits[name].window
            self._seen[name] = (max(limit - remaining, 0.0), self._clock() + (seconds_left or window))

    def block(self, name: str, seconds: float) -> None:
        """The gateway answered 429: leave it alone until its window says it is over."""
        self._blocked[name] = self._clock() + seconds

    def snapshot(self) -> dict[str, dict]:
        return {name: {"unit": limit.unit, "limit": limit.amount, "window_seconds": limit.window,
                       "used": round(self.used(name), 4), "cap": round(self.share * limit.amount, 4),
                       "percent": round(100 * self.used(name) / limit.amount, 2)}
                for name, limit in self._limits.items()}
