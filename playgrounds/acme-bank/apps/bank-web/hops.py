"""The hops of an answer, as Behind the answer draws them: one anatomy for every call that made the answer.

A hop is always the same four parts: a TITLE, three BADGES (the system the call went through, its status, its duration), ONE line that says what
happened, and the EVIDENCE of that call in Gamma (answers.py adds it); what the call held (a tool's arguments and result, a model's name and tokens)
is its `facts`, which the page keeps behind a "Details" disclosure.

Ace reports its own calls as a trace, one row each (the token exchange, the list of tools, each call to the model, each tool). The app makes the
others itself (the call to Ace, a payment, a team's call, a developer's call). All of them become the same shape here.

THE NAMING TABLE: one title for each kind of hop, "<actor> <verb> <object>". The page, the guide and the README use these words and no others.

    kind       title                                                  system             evidence
    a2a        <Person> asked Ace                                     A2A proxy          Trace, Logs
               Someone not signed in asked Ace                                                  (the call that carried no token: the gateway refuses it)
    exchange   Ace got a token for <Person>                           Access Management  none (AM is not behind the gateway)
    tools      Ace asked which tools it may use                       MCP proxy          Trace, Logs
    llm        Ace asked the model what to do                         LLM proxy          Trace, Logs   (the first call to the model)
               Ace asked the model again                                                               (a call that follows one, before any tool has answered)
               Ace asked the model for the answer                                                      (after a tool has answered)
    tool       Ace called <tool>                                      MCP proxy          Trace, Logs, Decisions
               <Person> called <tool>                                                                  (a payment made with no agent)
               Someone not signed in called <tool>                                                     (the same, with no token: the gateway refuses it)
    workspace  <Team> asked the AI workspace                          AI workspace       Trace, Logs, Spend
    llm        A developer asked the model                            LLM proxy          Trace, Logs   (the Developers key)

A call that went with no gateway says "No gateway" where the system goes, and has no evidence: nothing was recorded.
"""
import re
from typing import Any

from people import Persona
from upstream import clean

# outcome of a hop -> (tone the page colors it with, the word that says it: for a screen reader, and before the reason of a refusal)
OUTCOMES = {
    "ok": ("ok", "Answered"),
    "denied": ("deny", "Denied by policy"),
    "unauthorized": ("deny", "Unauthorized"),
    "blocked": ("block", "Blocked"),
    "rate_limited": ("limit", "Limited"),
    "error": ("error", "Error"),
}
STATUS_OUTCOMES = {400: "blocked", 401: "unauthorized", 403: "denied", 429: "rate_limited"}
SYSTEMS = {"a2a": "A2A proxy", "exchange": "Access Management", "tools": "MCP proxy", "llm": "LLM proxy", "tool": "MCP proxy", "workspace": "AI workspace"}
NO_GATEWAY = "No gateway"
NOBODY = "Someone not signed in"          # who asks when the call carries no token
NO_TOKEN = "no token was sent"            # why the gateway refused it: the reason of the hop of a call that carried none
APIS = {"a2a": "a2a", "tools": "mcp", "llm": "llm", "tool": "mcp", "workspace": "teams"}      # the API a hop went through: its request is in that API's logs and traces
TITLES = {
    "a2a": "{person} asked Ace",
    "exchange": "Ace got a token for {person}",
    "tools": "Ace asked which tools it may use",
    "first": "Ace asked the model what to do",
    "again": "Ace asked the model again",
    "later": "Ace asked the model for the answer",
    "tool": "Ace called {name}",
    "payment": "{person} called {name}",
    "workspace": "{team} asked the AI workspace",
    "developer": "A developer asked the model",
    "agent": "Ace could not finish",
}
LISTING = ("tools/list", "connect")        # Ace reads the tool list and connects without asking the policy engine: only a tool call is decided
SECRET = re.compile(r"token|secret|password|authorization|api[-_]?key", re.IGNORECASE)
TOKENS = re.compile(r"(\d+) tokens?")
DETAIL_LIMIT = 300
SUMMARY_LIMIT = 160


def whole(value: Any) -> int | None:
    """Numbers cross the A2A data part as floats: 12.0 becomes 12."""
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def clip(value: Any, limit: int = DETAIL_LIMIT) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _plain(value: Any) -> Any:
    return int(value) if isinstance(value, float) and value.is_integer() else value


def asked(raw: Any) -> dict[str, Any]:
    """What the tool was asked, as a dict, with anything that looks like a secret left out."""
    if not isinstance(raw, dict):
        return {}
    return {str(key): _plain(value) for key, value in raw.items() if not SECRET.search(str(key))}


def arguments(raw: Any) -> str:
    """What the tool was asked, in one line, with anything that looks like a secret left out."""
    return clip(", ".join(f"{key} {value}" for key, value in asked(raw).items()), 160)


def outcome_of(status: Any) -> str:
    """What a status says of a call the app made itself: 2xx went through, the others are refusals or failures."""
    code = whole(status)
    return "ok" if code is not None and 200 <= code < 300 else STATUS_OUTCOMES.get(code, "error")


def refusal(word: str, detail: str) -> str:
    """The one line of a hop that did not go through: what it was, then why."""
    detail = clip(detail, SUMMARY_LIMIT).strip()
    return f"{word}: {detail}" if detail and detail.rstrip(".").lower() != word.lower() else f"{word}."


def fact(label: str, value: Any, code: bool = False) -> dict:
    return {"label": label, "value": clip(value), "code": code}


def hop(kind: str, title: str, outcome: str, *, ok: str = "", detail: str = "", gateway: bool = True, status: Any = None, ms: Any = None,
        facts: list[dict] | None = None, name: str = "", transaction_id: str | None = None, request_id: Any = None, word: str | None = None) -> dict:
    """One hop, in the one shape the page draws. `ok` is its line when it went through, `detail` the reason when it did not; `word` says it
    in place of the status where there is none to say ("Reused")."""
    tone, said = OUTCOMES.get(outcome, ("note", clip(outcome, 40)))
    word = word or said
    system = SYSTEMS.get(kind)
    system = system if system is None or gateway or kind == "exchange" else NO_GATEWAY
    return {
        "kind": kind,
        "name": clip(name, 60),
        "title": title,
        "system": system,
        "direct": system == NO_GATEWAY,
        "outcome": outcome,
        "tone": tone,
        "word": word,
        "status": whole(status),
        "ms": whole(ms),
        "summary": clip(ok, SUMMARY_LIMIT) if outcome == "ok" else refusal(said, detail),
        "facts": [f for f in (facts or []) if f["value"]],
        "transaction_id": transaction_id,
        "request_id": clean(request_id),       # the gateway's id of the request of the hop: what its log, its trace and its decision are found by
        "api": APIS.get(kind),
    }


# -- the calls the app makes itself ---------------------------------------------------------------------------------------------

def name_of(person: Persona | None) -> str:
    """Who a call is of, as the title of its hop says it: the person's first name, or nobody's when the call carried no token."""
    return person.first if person else NOBODY


def asked_ace(person: Persona | None, *, gateway: bool, status: Any, ms: Any, transaction_id: str | None = None, request_id: Any = None, detail: str = "",
              calls: int = 0) -> dict:
    """The call that brought the question to Ace, through the A2A proxy or straight to it: the first hop of every answer. It lasted as long as the
    answer took, the `calls` Ace made meanwhile (the hops below it) included: its line says so."""
    said = f"Ace answered after the {calls} calls below." if calls > 1 else "Ace answered after the call below." if calls else "Ace answered."
    return hop("a2a", TITLES["a2a"].format(person=name_of(person)), outcome_of(status), ok=said, detail=detail,
               gateway=gateway, status=status, ms=ms, transaction_id=transaction_id, request_id=request_id)


def payment(person: Persona | None, name: str, args: dict, outcome: str, detail: str, *, gateway: bool, status: Any, ms: Any,
            transaction_id: str | None, request_id: Any) -> dict:
    """The person's own call of a tool, with no agent in between (nobody's, when it carried no token)."""
    facts = [fact("Asked", arguments(args), True), fact("Result", detail, True) if outcome == "ok" else None]
    return hop("tool", TITLES["payment"].format(person=name_of(person), name=clip(name, 60)), outcome, ok="The bank's tool answered.", detail=detail,
               gateway=gateway, status=status, ms=ms, facts=[f for f in facts if f], name=name, transaction_id=transaction_id, request_id=request_id)


def answer_of(result: dict, title: str, kind: str) -> dict:
    """A call of the LLM proxy or of an AI workspace, as `llm.complete` reports it."""
    model, tokens = result.get("model"), result.get("tokens") or {}
    total = whole(tokens.get("total"))
    if result.get("cached"):
        said = "The semantic cache answered."
    else:
        said = f"The {model} model answered{f', {total:,} tokens' if total else ''}." if model else "The model answered."
    facts = [fact("Model", model), fact("Tokens", f"{total:,}" if total else "")]
    # What the gateway refused with is the answer itself, which the turn shows: the hop says the word, not the sentence again
    return hop(kind, title, outcome_of(result.get("status")), ok=said, status=result.get("status"), ms=result.get("ms"),
               facts=facts, name=model or "", transaction_id=result.get("transaction_id"), request_id=result.get("request_id"))


def workspace(result: dict, team: str) -> dict:
    return answer_of(result, TITLES["workspace"].format(team=team), "workspace")


def developer(result: dict) -> dict:
    return answer_of(result, TITLES["developer"], "llm")


# -- Ace's own trace ------------------------------------------------------------------------------------------------------------

def _kind(step: dict) -> str:
    if step.get("step") == "tool":
        return "tools" if step.get("name") in LISTING else "tool"
    return step.get("step") if step.get("step") in ("llm", "exchange") else "agent"


def _chose(steps: list[dict], index: int) -> list[str]:
    """The tools the model chose in the call at `index`: the tool calls that follow it, up to its next call."""
    chosen = []
    for later in steps[index + 1:]:
        if later.get("step") == "llm":
            break
        if _kind(later) == "tool":
            chosen.append(clip(later.get("name"), 60))
    return chosen


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def _listing(step: dict, offered: list[str] | None, catalog: list[str] | None) -> tuple[str, list[dict]]:
    """What Ace may use of the bank's tools: out of every tool the bank has, those it was offered, with the ones it was not named."""
    if offered is None:
        return (f"Ace may use {step['detail']}." if step.get("detail") else "Ace listed the tools."), []
    facts = [fact("Offered", ", ".join(offered), True)]
    if not catalog:
        return f"Ace may use {len(offered)} tool{'' if len(offered) == 1 else 's'}.", facts
    hidden = [name for name in catalog if name not in offered]
    return f"Ace may use {len(offered)} of {len(catalog)} tools" + (f", not {_and(hidden)}" if hidden else "") + ".", facts


def _token(step: dict, person: Persona, claims: dict | None, common: dict) -> dict:
    """The token Ace got for the person: issued by Access Management for this question, or kept from an earlier one, in which case Access Management was
    not asked and the hop has no status and no time to show (its word is "Reused"). What Ace did not say the claims of, and a failure, are in Ace's own words."""
    act = claims.get("act") if isinstance(claims, dict) else None
    actor = clip(act.get("sub"), 60) if isinstance(act, dict) and act.get("sub") else ""
    title, name = TITLES["exchange"].format(person=person.first), clip(step.get("name"), 60)
    if not actor or common["outcome"] != "ok":
        return hop("exchange", title, name=name, ok=common["detail"], **common)
    reused = common["detail"].startswith("reused")
    who = f"sub {person.first}, acting agent {actor}"
    facts = [fact("Subject", person.name), fact("Acting agent", actor),
             fact("Token", "Kept from an earlier question, still valid" if reused else "Issued by Access Management for this question")]
    if reused:
        return hop("exchange", title, name=name, ok=f"Ace used the token it got earlier: {who}.", facts=facts, **{**common, "status": None, "ms": None, "word": "Reused"})
    return hop("exchange", title, name=name, ok=f"Access Management issued it: {who}.", facts=facts, **common)


def rows(trace: Any, *, person: Persona, gateway: bool, claims: dict | None = None, offered: list[str] | None = None,
         catalog: list[str] | None = None) -> list[dict]:
    """Ace's trace as hops. The model's calls say why Ace made them (what to do until a tool has answered, the answer after it) and what the model
    decided (read from what follows: the tools it chose, else the answer); the tools Ace may use are those it listed, out of the bank's catalog."""
    steps = [s for s in trace if isinstance(s, dict)] if isinstance(trace, list) else []
    last_model = max((i for i, s in enumerate(steps) if s.get("step") == "llm"), default=-1)
    out, answered, asked_model = [], False, False
    for index, step in enumerate(steps):
        kind, detail, name = _kind(step), clip(step.get("detail")), clip(step.get("name"), 60)
        common = dict(outcome=step.get("outcome", ""), detail=detail, gateway=gateway, status=step.get("status"), ms=step.get("ms"),
                      transaction_id=step.get("transaction_id"), request_id=step.get("request_id"))
        if kind == "llm":
            chosen = _chose(steps, index)
            ok = f"The model chose {_and(chosen)}." if chosen else "The model wrote the answer." if index == last_model else "The model chose no tool."
            tokens = TOKENS.search(detail)
            facts = [fact("Model", name), fact("Tokens", f"{int(tokens.group(1)):,}" if tokens else "")]
            out.append(hop("llm", TITLES["later" if answered else "again" if asked_model else "first"], ok=ok, facts=facts, name=name, **common))
            asked_model = True
        elif kind == "tool":
            answered = True
            args = arguments(step.get("arguments"))
            facts = [fact("Asked", args, True), fact("Result", detail, True) if step.get("outcome") == "ok" else None]
            out.append(hop("tool", TITLES["tool"].format(name=name), ok="The bank's tool answered.", facts=[f for f in facts if f], name=name, **common))
        elif kind == "tools":
            line, facts = _listing(step, offered, catalog)
            out.append(hop("tools", TITLES["tools"], ok=line, facts=facts, name=name, **common))
        elif kind == "exchange":
            out.append(_token(step, person, claims, common))
        else:
            out.append(hop("agent", TITLES["agent"], name=name, **{**common, "outcome": step.get("outcome") or "error"}))
    return out
