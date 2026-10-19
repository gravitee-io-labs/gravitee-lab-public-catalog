"""Money the generator moved, and giving it back.

The bank's balances are what the guide quotes, and a transfer is the one thing that changes them. So every transfer
is followed by the opposite one, made by the owner of the account that received it, with their own token: the
balances end where they started. A transfer that could not be given back yet stays here and is tried again after
every scenario, and no new transfer starts until it is settled.

A call that moves money can end without an answer: the gateway gives up after 30 s while the bank has already done
it, or a scenario is cut. Neither the trace nor a reply says what happened then, but the balances do. A scenario that
may move money is watched: its balances are read first, and when it ends without an answer they are read again and
what moved is owed like any other transfer.
"""
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from cast import ACCOUNT_OWNERS
from clients import Tools
from wire import PlatformError

log = logging.getLogger("bank-traffic")
CENT = 0.005
UNEXPLAINED_KEPT = 5       # how many of the balances that moved with no transfer to explain them /status keeps


@dataclass
class Owed:
    source: str        # the account the money left
    target: str        # the account that received it
    amount: float
    seen: float | None = None      # the balance of `target` before a give-back that got no answer (see _give_back)


def whole(amount: float) -> float | int:
    """120.0 is sent as 120, as a person's app would."""
    return int(amount) if float(amount).is_integer() else amount


class Transfers:
    def __init__(self, tools: Tools) -> None:
        self._tools = tools
        self.owed: list[Owed] = []
        self.moved = self.returned = 0.0
        self.unexplained: list[str] = []
        self._expected: dict[str, float] | None = None      # the balances a watched scenario should end with

    def note(self, source: str, target: str, amount: float) -> None:
        """A transfer went through: it is owed back."""
        self.owed.append(Owed(source, target, float(amount)))
        self.moved += float(amount)
        if self._expected is not None:         # a watched scenario knows what it did: it is no surprise
            for account, change in ((source, -float(amount)), (target, float(amount))):
                if account in self._expected:
                    self._expected[account] += change

    def note_trace(self, trace: list[dict[str, Any]]) -> None:
        """Ace's transfers, read from its trace: whatever the model decided to move, in whatever amount."""
        for row in trace:
            arguments = row.get("arguments") or {}
            if row.get("step") == "tool" and row.get("name") == "transfer_funds" and row.get("outcome") == "ok":
                self.note(str(arguments.get("from_account")), str(arguments.get("to_account")),
                          arguments.get("amount") or 0)

    # --- Reading the balances ------------------------------------------------------------------------------------

    async def balances(self) -> dict[str, float]:
        """The balance of every account of the cast, each read by its owner. Raises PlatformError when one cannot be."""
        return {account: await self._balance(owner, account) for account, owner in ACCOUNT_OWNERS.items()}

    async def _balance(self, owner: str, account: str) -> float:
        reply = await self._tools.call(owner, "get_balance", {"account_id": account})
        if reply.outcome == "ok":
            with contextlib.suppress(ValueError, KeyError, TypeError):
                return float(json.loads(reply.detail)["balance"])
        raise PlatformError(f"the balance of {account} cannot be read as {owner}: {reply.outcome} {reply.detail}")

    @contextlib.asynccontextmanager
    async def watch(self) -> AsyncIterator[None]:
        """Around a scenario that may move money. If it ends in an error, or is cut, whatever moved that it did not
        note is found in the balances and owed back."""
        self._expected = await self.balances()
        try:
            yield
        except Exception:
            await self._find_what_moved()
            raise
        finally:
            self._expected = None

    async def _find_what_moved(self) -> None:
        expected = self._expected
        if expected is None:         # the bank is reset meanwhile: its balances say nothing about the scenario
            return
        try:
            after = await self.balances()
        except PlatformError as e:
            self._doubt(f"a scenario ended without an answer and the balances could not be read to tell what it "
                        f"moved ({e})")
            return
        moved = {account: round(after[account] - expected[account], 2) for account in after}
        moved = {account: change for account, change in moved.items() if change}
        sources = [account for account, change in moved.items() if change < 0]
        targets = [account for account, change in moved.items() if change > 0]
        if len(sources) == 1 and len(targets) == 1 and moved[sources[0]] == -moved[targets[0]]:
            log.warning("a scenario ended without an answer after %s EUR went from %s to %s: owed back",
                        whole(moved[targets[0]]), sources[0], targets[0])
            self.note(sources[0], targets[0], moved[targets[0]])
        elif moved:
            self._doubt("a scenario ended without an answer and the balances moved with no single transfer to "
                        "explain it: " + ", ".join(f"{account} {change:+.2f}" for account, change in moved.items()))

    def _doubt(self, message: str) -> None:
        """What cannot be given back by the generator: said in the log and in /status until the bank is started over."""
        log.warning("%s; Start the bank over restores the balances", message)
        self.unexplained.append(message)
        del self.unexplained[:-UNEXPLAINED_KEPT]

    # --- Giving back ---------------------------------------------------------------------------------------------

    async def settle(self) -> None:
        for debt in list(self.owed):
            owner = ACCOUNT_OWNERS.get(debt.target)
            if owner is None:
                log.warning("transfer of %s EUR from %s to %s cannot be given back: nobody of the cast owns %s",
                            whole(debt.amount), debt.source, debt.target, debt.target)
                self.owed.remove(debt)
                continue
            try:
                back = await self._give_back(debt, owner)
            except PlatformError as e:
                log.warning("transfer of %s EUR back to %s is still owed: %s", whole(debt.amount), debt.source, e)
                return
            if not back:
                return
            self.owed.remove(debt)
            self.returned += debt.amount
            log.info("gave back %s EUR to %s", whole(debt.amount), debt.source)

    async def _give_back(self, debt: Owed, owner: str) -> bool:
        """The opposite transfer, made by the owner of the account that has the money. A call that got no answer may
        have gone through, and sending it again would move the money a second time: so the balance of that account
        is read before each attempt, and after one that got no answer it says whether the money left."""
        paying = await self._balance(owner, debt.target)
        if debt.seen is not None and paying <= debt.seen - debt.amount + CENT:
            return True
        debt.seen = paying
        reply = await self._tools.call(owner, "transfer_funds", {
            "from_account": debt.target, "to_account": debt.source, "amount": whole(debt.amount)})
        if reply.outcome == "ok":
            return True
        debt.seen = None            # the bank answered, so it did not move the money
        log.warning("transfer of %s EUR back to %s is still owed: %s %s", whole(debt.amount), debt.source,
                    reply.outcome, reply.detail)
        return False

    def reset(self) -> None:
        """After a reset of the bank nothing is owed: giving money back would move money that is not there."""
        self.owed.clear()
        self.unexplained.clear()
        self.moved = self.returned = 0.0
        self._expected = None

    def status(self) -> dict[str, Any]:
        return {"moved_eur": self.moved, "returned_eur": self.returned,
                "owed": [{"from": d.source, "to": d.target, "amount_eur": d.amount} for d in self.owed],
                "unexplained": list(self.unexplained)}
