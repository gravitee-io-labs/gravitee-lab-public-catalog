"""The model: the OpenAI SDK against the gateway's LLM proxy, or against Ollama for the direct Ace. No streaming."""
import json
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any

import httpx2
import openai
from openai import AsyncOpenAI

from gateway import TRANSACTION_HEADER, message_of, try_again, wait_seconds
from settings import Settings
from steps import elapsed_ms

TEMPERATURE = 0.2
TIMEOUT = 60                # seconds: a local model is slow at its first answer
NO_KEY = "none"             # the SDK refuses an empty key, and a model reached directly ignores it
BLOCKED = "I can't help with that: the request was blocked by ACME's AI policy."
UNAVAILABLE = "The AI model is not available right now."

# A small model sometimes writes its tool call as text instead of using the tool-call channel
TEXT_TOOL_CALL = re.compile(r"<(?:tool_call|tool)>\s*(\{.*?\})\s*</(?:tool_call|tool)>", re.DOTALL)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str          # as the model wrote it: JSON text, maybe not valid


@dataclass(frozen=True)
class Completion:
    content: str
    tool_calls: list[ToolCall]
    tokens: int
    status: int
    ms: int
    headers: dict[str, str] = field(default_factory=dict)


class LlmError(Exception):
    """The model gave no answer: what to tell the user, and what the trace shows."""

    def __init__(self, outcome: str, answer: str, detail: str, ms: int,
                 status: int | None = None, headers: dict[str, str] | None = None) -> None:
        super().__init__(detail)
        self.outcome, self.answer, self.detail, self.ms, self.status = outcome, answer, detail, ms, status
        self.headers = headers or {}


class Llm:
    def __init__(self, settings: Settings, http_client: httpx2.AsyncClient | None = None) -> None:
        self.model = settings.llm_model
        self.reasoning_effort = settings.llm_reasoning_effort
        key = settings.llm_api_key
        # The SDK sends the key as Authorization: Bearer, which a BEARER plan and a workspace plan both read.
        # max_retries=0: the SDK would retry a 429 or a 5xx twice and wait out the limit, which hides it.
        self.client = AsyncOpenAI(base_url=settings.llm_url, api_key=key or NO_KEY, timeout=TIMEOUT, max_retries=0,
                                  http_client=http_client)

    async def aclose(self) -> None:
        await self.client.close()

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]],
                       transaction_id: str | None = None) -> Completion:
        request: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": TEMPERATURE}
        if tools:
            request["tools"] = tools
        if self.reasoning_effort:
            request["reasoning_effort"] = self.reasoning_effort
        started = time.monotonic()
        try:
            raw = await self.client.chat.completions.with_raw_response.create(
                **request, extra_headers={TRANSACTION_HEADER: transaction_id} if transaction_id else None)
            answer = raw.parse()
        except openai.APIStatusError as e:
            raise refusal(e, elapsed_ms(started)) from e
        except openai.APIError as e:                      # no connection, no answer in time, an unreadable body
            raise LlmError("error", UNAVAILABLE, type(e).__name__, elapsed_ms(started)) from e
        if not answer.choices:
            raise LlmError("error", UNAVAILABLE, "the model answered nothing", elapsed_ms(started), raw.status_code)
        message = answer.choices[0].message
        calls = [ToolCall(c.id, c.function.name, c.function.arguments or "{}")
                 for c in message.tool_calls or [] if c.type == "function"]
        completion = Completion(message.content or "", calls, answer.usage.total_tokens if answer.usage else 0,
                                raw.status_code, elapsed_ms(started), dict(raw.headers))
        return repair_text_tool_call(completion, {t["function"]["name"] for t in tools})


def refusal(error: openai.APIStatusError, ms: int) -> LlmError:
    """The gateway's answer to a call it refused: the guard rails (400, 403), a limit (429), anything else."""
    status, headers = error.status_code, dict(error.response.headers)
    detail = message_of(error.body, f"HTTP {status}")
    if status in (400, 403):
        return LlmError("blocked", BLOCKED, detail, ms, status, headers)
    if status == 429:
        answer = f"The AI usage limit is reached.{try_again(wait_seconds(headers))}"
        return LlmError("rate_limited", answer, detail, ms, status, headers)
    return LlmError("error", UNAVAILABLE, detail, ms, status, headers)


def without_tool_calls(text: str) -> str:
    """The answer without a tool call written as text: one the user may not use is not an answer to show."""
    return TEXT_TOOL_CALL.sub("", text).strip()


def repair_text_tool_call(completion: Completion, offered: set[str]) -> Completion:
    """Turn a tool call written as text into a real one, for a tool that was offered only."""
    found = None if completion.tool_calls else TEXT_TOOL_CALL.search(completion.content)
    if not found:
        return completion
    try:
        call = json.loads(found.group(1))
    except ValueError:
        return completion
    if not isinstance(call, dict):
        return completion
    name, arguments = call.get("name"), call.get("arguments", {})
    if name not in offered or not isinstance(arguments, dict):
        return completion
    return replace(completion, content="", tool_calls=[ToolCall("call_repaired", name, json.dumps(arguments))])
