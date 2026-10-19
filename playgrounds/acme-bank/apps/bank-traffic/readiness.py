"""What the generator waits for: the platform doing the things it is about to ask of it.

Nothing here depends on the order the containers start in, or on a file: each prerequisite is a small real request.
A seed that is still running, a gateway that restarts, a workspace somebody deleted: all of it shows as a reason for
waiting, and the traffic starts, or goes on, when the reason is gone.
"""
from typing import Awaitable, Callable

from cast import ALL_TOOL_COUNT, CUSTOMER_TOOL_COUNT, TEAMS
from clients import Ace, Llm, Teams, Tools
from wire import PlatformError

LLM, MCP, A2A, WORKSPACE = "llm", "mcp", "a2a", "workspace"
Probe = Callable[[], Awaitable[None]]       # returns when the prerequisite holds, raises PlatformError when not


class Readiness:
    def __init__(self, probes: dict[str, Probe]) -> None:
        self._probes = probes
        self._reasons: dict[str, str | None] = {name: "not checked yet" for name in probes}

    @property
    def ready(self) -> set[str]:
        return {name for name, reason in self._reasons.items() if reason is None}

    @property
    def waiting(self) -> dict[str, str]:
        return {name: reason for name, reason in self._reasons.items() if reason is not None}

    async def check(self) -> None:
        """Asks again what is not ready. What is ready stays so until a scenario finds it is not."""
        for name, probe in self._probes.items():
            if self._reasons[name] is not None:
                self._reasons[name] = await reason_of(probe)

    def mark_down(self, name: str, reason: str) -> None:
        self._reasons[name] = reason


async def reason_of(probe: Probe) -> str | None:
    try:
        await probe()
    except PlatformError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001 - a probe must never end the generator
        return f"{type(e).__name__}: {e}"
    return None


def probes(llm: Llm, tools: Tools, ace: Ace, teams: Teams, strict: bool = False) -> dict[str, Probe]:
    async def llm_answers() -> None:
        status = await llm.models()
        if status != 200:
            raise PlatformError(f"the LLM proxy answered HTTP {status} to the Traffic key", status)

    async def identity_and_policies_are_live() -> None:
        # Alice sees 7 tools while Tools by role is on and 8 while it is off (the playground starts it off, and the generator
        # accepts either, unless PROTECTIONS=on says everything is protected); either way AM signed her in and the plan accepted
        # her token. A public tool then proves the authorization policies are loaded, so the traffic does not start by filling
        # the decision log with denials of a platform that is not ready
        listed = await tools.names("alice")
        expected = (CUSTOMER_TOOL_COUNT,) if strict else (CUSTOMER_TOOL_COUNT, ALL_TOOL_COUNT)      # with the protections on, 7 and no other
        if len(listed) not in expected:
            raise PlatformError(f"the MCP proxy lists {len(listed)} tools to alice, expected {' or '.join(map(str, expected))}")
        reply = await tools.call("alice", "get_exchange_rate", {"base": "EUR", "quote": "USD", "amount": 1})
        if reply.outcome != "ok":
            raise PlatformError(f"a public tool was not permitted to alice: {reply.outcome} {reply.detail}")

    async def ace_card_is_served() -> None:
        await ace.reachable("alice")

    async def workspace_is_deployed() -> None:
        await teams.reload(deployed=True)
        for team in TEAMS:
            await teams.reachable(team)

    return {LLM: llm_answers, MCP: identity_and_policies_are_live,
            A2A: ace_card_is_served, WORKSPACE: workspace_is_deployed}


def describe(waiting: dict[str, str]) -> str:
    return "; ".join(f"{name}: {reason}" for name, reason in waiting.items())
