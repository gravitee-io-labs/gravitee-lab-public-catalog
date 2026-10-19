"""What an answer carries besides its text: the hops of the call, each with the evidence that shows it in Gamma.

The evidence is the platform's own, and a hop has its own: the trace and the log entry of THAT call, the decision of the policy engine about a tool
call, and, for a team's call, what the run spent. Each is a route of this app that finds the exact item in Gamma when its button is pressed
(evidence.py). A hop that went with no gateway was recorded nowhere, and the token exchange is Access Management's, not the gateway's: they have none.
"""
import time

from bounds import SPAN
from evidence import route

LABELS = {"trace": "Trace", "logs": "Logs", "decisions": "Decisions", "spend": "Spend"}       # the buttons of a hop, always in this order


def evidence(**urls: str | None) -> list[dict]:
    """The links that exist, always in the same order (Trace, Logs, Decisions, Spend: a person finds each where it was)."""
    return [{"kind": kind, "label": label, "url": urls[kind]} for kind, label in LABELS.items() if urls.get(kind)]


class Answers:
    def __init__(self, now=time.time):
        self.now = now

    def _at(self) -> int:
        return int(self.now() * 1000)

    def hop(self, row: dict, since: int | None = None) -> dict:
        """A hop with the buttons of its own call: Trace and Logs for every call that went through a gateway API (the A2A, LLM and MCP proxies, an AI
        workspace), Decisions for a tool call (the policy engine decides each of them, unless the OAuth2 plan refused the call first: a 401 was never put to it),
        Spend for a team's call (from when its run began, `since`, else from when this call began). A call with no request id of the gateway has none."""
        api, request, at = row.get("api"), row.get("request_id"), self._at()
        if not (api and request):
            return {**row, "evidence": []}
        urls = {"trace": route("trace", api, request, at), "logs": route("logs", api, request, at)}
        if row.get("kind") == "tool" and row.get("status") != 401:
            urls["decisions"] = route("decisions", "mcp", request, at)
        if row.get("kind") == "workspace":
            urls["spend"] = route("spend", "teams", request, at, since if since is not None else self._began(row))
        return {**row, "evidence": evidence(**urls)}

    def turn(self, turn: dict) -> dict:
        """A turn with Ace: every hop with its evidence."""
        return {**turn, "rows": [self.hop(row) for row in turn["rows"]]}

    def payment(self, row: dict) -> dict:
        """A payment the person made with their own token: one hop."""
        return self.hop(row)

    def call(self, result: dict, row: dict, since: int | None = None) -> dict:
        """An answer of the LLM proxy or of the AI workspace, as the one hop it is."""
        return {**result, "rows": [self.hop(row, since)]}

    def _began(self, row: dict) -> int | None:
        """When a call began: now less what it took, however long that was. None where the call does not say how long it took."""
        took = row.get("ms")
        return self._at() - min(max(took, 0), SPAN) if isinstance(took, int) and not isinstance(took, bool) else None
