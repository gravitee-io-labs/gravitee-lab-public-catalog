"""One chat turn: the user's question to the model, the model's tool calls to the bank, the answer, and what happened.

Ace acts for the signed-in user. Its prompt comes from the claims of the user's token; the bank's tools are called
with a token that says "the user, through Ace" (see identity.py), so the gateway decides with the user's rights and
Ace's cap. When that token cannot be had, Ace does not act: with the user's own token the cap would not apply.
"""
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx2
from mcp import MCPError

from gateway import Hop, HopRecorder, ids_of, try_again, wait_seconds
from identity import Delegation, DelegationError, jwt_claims
from llm import Completion, Llm, LlmError, without_tool_calls
from prompt import build_system
from settings import Settings
from steps import Trace, elapsed_ms, log
from tools import (INVALID_ARGUMENTS, EXPIRED, TIMED_OUT, UNREACHABLE, ToolResult, call_tool, list_tools,
                   open_session, parse_arguments)

MAX_TURNS = 4                   # calls of the model for one question
# The nudge is a user turn that the guard rails score with the rest, so it is a plain request: an order such as
# "Do not answer without one." can get an ordinary question blocked as an injection
NUDGE = "Use a tool to get the data."
# A small model that left out a required argument answers in words when it only reads the validation error; asked
# once more as a user turn it calls the tool again with the argument
MISSING_ARGUMENT = re.compile(r"field required", re.IGNORECASE)
CALL_AGAIN = "Call the tool again with the missing argument."
# Questions a small model answers from memory, or by asking for an id it already has: asked once more, with the nudge
NUDGE_WORDS = re.compile(r"\b(?:balance|account|money|transaction|saving|spen[dt]|send|transfer|pay|exchange|convert|rate|loan|mortgage|branch)", re.IGNORECASE)
EMPTY_ANSWER = "I cannot help with that request. A teller in a branch can."
GAVE_UP = "I could not finish that request. Please rephrase it."
NO_QUESTION = "What can I help you with?"
BROKEN = "Something went wrong on my side. Try again in a moment."
NOT_AN_OBJECT = "The arguments were not a JSON object."
NOT_ALLOWED = "You are not allowed to use the bank's tools."
CANNOT_ACT = "I cannot act for you right now. Try again in a moment."


@dataclass(frozen=True)
class Reply:
    answer: str
    data: dict[str, Any]        # the data part of the A2A message: trace, tools, delegated_claims


class Turn:
    """What a turn learns on the way, for the data part of its reply."""

    def __init__(self) -> None:
        self.trace = Trace()
        self.tools: list[str] = []                          # what the user may use, from tools/list
        self.delegated_claims: dict[str, Any] | None = None

    def data(self) -> dict[str, Any]:
        data: dict[str, Any] = {"trace": self.trace.rows, "tools": self.tools}
        if self.delegated_claims:
            data["delegated_claims"] = self.delegated_claims
        return data


class Ace:
    def __init__(self, settings: Settings, llm: Llm, delegation: Delegation | None = None,
                 mcp_transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self.settings, self.llm, self.delegation, self.mcp_transport = settings, llm, delegation, mcp_transport

    @classmethod
    def from_settings(cls, settings: Settings) -> "Ace":
        return cls(settings, Llm(settings), Delegation(settings) if settings.delegation else None)

    async def aclose(self) -> None:
        await self.llm.aclose()
        if self.delegation:
            await self.delegation.aclose()

    async def reply(self, question: str, bearer: str | None, transaction_id: str | None = None) -> Reply:
        """Answers one message. Whatever goes wrong becomes a sentence and a row of the trace, never an exception.
        `transaction_id` is the one the gateway gave the call that brought the question: Ace sends it on every call it
        makes to the gateway for this turn, and Logs then shows the whole turn under it."""
        turn = Turn()
        if not question.strip():
            return Reply(NO_QUESTION, turn.data())
        try:
            answer = await self._answer(question, bearer, turn, transaction_id)
        except Exception:  # noqa: BLE001 - whatever goes wrong becomes a sentence and a row of the trace
            log.exception("the turn failed")
            turn.trace.add("agent", "turn", "error", 0, "unexpected error")
            answer = BROKEN
        return Reply(answer, turn.data())

    async def _answer(self, question: str, bearer: str | None, turn: Turn, transaction_id: str | None) -> str:
        try:
            token = await self._tools_token(bearer, turn)
        except DelegationError:         # the row says why; no model call, no tool call
            return CANNOT_ACT
        system = build_system(jwt_claims(bearer or ""), question)
        recorder, started = HopRecorder(), time.monotonic()
        try:
            async with open_session(self.settings.mcp_url, token, recorder, self.mcp_transport, transaction_id) as mcp:
                tools, listing = await list_tools(mcp, recorder)
                turn.tools = [tool["function"]["name"] for tool in tools]
                add_tool_row(turn.trace, "tools/list", listing)
                answer = await self._converse(question, system, tools, mcp, recorder, turn.trace, transaction_id)
        except* (MCPError, httpx2.HTTPError):       # the session could not start, or broke off: it arrives in a group
            answer = session_failed(recorder.last, turn.trace, elapsed_ms(started))
        return answer

    async def _tools_token(self, bearer: str | None, turn: Turn) -> str | None:
        """The token the bank's tools get: the delegated one, or the user's own when DELEGATION is off.

        With delegation on, a failed exchange is an error: the user's own token would work at the bank, but without the
        agent's limits."""
        if not bearer or self.delegation is None:
            return bearer
        started = time.monotonic()
        try:
            delegated = await self.delegation.delegated(bearer)
        except DelegationError as e:
            turn.trace.add("exchange", "token-exchange", "error", elapsed_ms(started),
                           f"{e}. No tool was called.", status=e.status)
            raise
        turn.trace.add("exchange", "token-exchange", "ok", elapsed_ms(started),
                       f"{'reused' if delegated.cached else 'issued'}: sub = the user, "
                       f"act.sub = {delegated.claims['act']['sub']}", status=200)
        turn.delegated_claims = delegated.claims
        return delegated.token

    async def _converse(self, question: str, system: str, tools: list[dict[str, Any]], mcp: Any,
                        recorder: HopRecorder, trace: Trace, transaction_id: str | None) -> str:
        try:
            return await self._loop(question, system, tools, mcp, recorder, trace, transaction_id)
        except LlmError as e:           # the guard rails blocked it, a limit was reached, or the model is down
            trace.add("llm", self.llm.model, e.outcome, e.ms, e.detail, status=e.status, **ids_of(e.headers),
                      blocked_by="llm-proxy" if e.outcome == "blocked" else None)
            return e.answer

    async def _loop(self, question: str, system: str, tools: list[dict[str, Any]], mcp: Any,
                    recorder: HopRecorder, trace: Trace, transaction_id: str | None) -> str:
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": question}]
        nudged = used_tools = asked_again = False
        bad_arguments = 0
        missing_argument = False
        for _ in range(MAX_TURNS):
            completion = await self.llm.complete(messages, tools, transaction_id)
            add_llm_row(trace, self.llm.model, completion)
            if not completion.tool_calls:
                if tools and not (used_tools or nudged) and NUDGE_WORDS.search(question):
                    nudged = True
                    messages += [assistant_message(completion), {"role": "user", "content": NUDGE}]
                    continue
                return without_tool_calls(completion.content) or EMPTY_ANSWER
            used_tools = True
            messages.append(assistant_message(completion))
            for call in completion.tool_calls:
                arguments = parse_arguments(call.arguments)
                if arguments is None:
                    bad_arguments += 1
                    result = ToolResult("error", INVALID_ARGUMENTS, NOT_AN_OBJECT, 0)
                else:
                    result = await call_tool(mcp, recorder, call.name, arguments)
                add_tool_row(trace, call.name, result, arguments or {})
                if bad_arguments > 1:               # the model had its one retry
                    return GAVE_UP
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result.content})
                if result.outcome == "error" and MISSING_ARGUMENT.search(result.content) and not asked_again:
                    asked_again = True
                    missing_argument = True
            if missing_argument:
                missing_argument = False
                messages.append({"role": "user", "content": CALL_AGAIN})
        return GAVE_UP


def assistant_message(completion: Completion) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": completion.content}
    if completion.tool_calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
            for c in completion.tool_calls]
    return message


def add_llm_row(trace: Trace, model: str, completion: Completion) -> None:
    trace.add("llm", model, "ok", completion.ms,
              f"{completion.tokens} tokens, {len(completion.tool_calls)} tool call(s)",
              status=completion.status, **ids_of(completion.headers))


def add_tool_row(trace: Trace, name: str, result: ToolResult, arguments: dict[str, Any] | None = None) -> None:
    trace.add("tool", name, result.outcome, result.ms, result.detail, arguments=arguments, status=result.status,
              **result.ids)


def session_failed(hop: Hop | None, trace: Trace, ms: int) -> str:
    """The session with the bank's tools could not start or broke off: say why, in a sentence the user can act on."""
    if hop is None:
        outcome, answer = "error", UNREACHABLE
    elif hop.status == 401:
        outcome, answer = "error", EXPIRED
    elif hop.status == 403:
        outcome, answer = "denied", hop.message or NOT_ALLOWED
    elif hop.status == 429:
        outcome, answer = "rate_limited", f"Too many requests.{try_again(wait_seconds(hop.headers))}"
    elif hop.status == 504:
        outcome, answer = "error", TIMED_OUT
    else:
        outcome, answer = "error", UNREACHABLE
    trace.add("tool", "connect", outcome, ms, answer, status=hop.status if hop else None, **(hop.ids if hop else {}))
    return answer
