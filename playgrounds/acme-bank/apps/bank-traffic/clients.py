"""The calls of the generator, each with the official SDK of its protocol: A2A to Ace, MCP to the bank's tools, and
the OpenAI client to a model. All of them go through the gateway, as a customer of the bank would."""
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Mapping

import httpx
import httpx2
import openai
from a2a.client import ClientCallContext, ClientConfig, create_client
from a2a.helpers import get_data_parts, get_message_text, new_message, new_text_part
from a2a.types import AgentCard, AgentInterface, Role, SendMessageRequest
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from openai import AsyncOpenAI

from settings import Settings
from tokens import Tokens
from wire import USER_AGENT, Hop, PlatformError, message_of
from workspace import Workspace

TIMEOUT = 60                         # seconds: a local model is slow at its first answer
CHAT_TIMEOUT = 90                    # seconds for Ace: its turn holds a model call, a tool call and a second model call
CACHE_ANSWER_ID = "resp_llmproxy"    # the id the gateway gives an answer it took from its semantic cache


def leaf(error: BaseException) -> BaseException:
    """The MCP client raises inside a task group: what went wrong is the first exception of the group."""
    while isinstance(error, BaseExceptionGroup):
        error = error.exceptions[0]
    return error


# --- Ace, over A2A ---------------------------------------------------------------------------------------------

@dataclass
class Reply:
    text: str
    trace: list[dict[str, Any]]      # one row per hop of Ace: llm, exchange, tool


class Ace:
    """The A2A client of the bank's agent through the gateway. The agent card is built here, not fetched: behind an
    OAuth2 plan the card itself needs the token, and the gateway rewrites the address in it anyway."""

    def __init__(self, settings: Settings, tokens: Tokens, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._url, self._tokens, self._hop = settings.ace_url, tokens, Hop()
        self._http = httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(30, read=CHAT_TIMEOUT),
                                       transport=transport, event_hooks={"response": [self._hop]})
        self._sdk = None

    async def reachable(self, persona: str) -> None:
        """The agent card, through the A2A proxy, with the user's token: free, and it needs the plan and the sign-in."""
        headers = {"Authorization": f"Bearer {await self._tokens.get(persona)}"}
        try:
            answer = await self._http.get(self._url + ".well-known/agent-card.json", headers=headers)
        except httpx.HTTPError as e:
            raise PlatformError(f"the A2A proxy does not answer ({type(e).__name__})") from e
        if answer.status_code != 200:
            raise PlatformError(f"the A2A proxy answered HTTP {answer.status_code} for the agent card",
                                answer.status_code)

    async def chat(self, persona: str, text: str) -> Reply:
        """One new conversation with Ace as the user. A dead token is replaced once."""
        try:
            return await self._send(await self._tokens.get(persona), text)
        except PlatformError as e:
            if e.status != 401:
                raise
            self._tokens.forget(persona)
            return await self._send(await self._tokens.get(persona), text)

    async def _send(self, token: str, text: str) -> Reply:
        if self._sdk is None:
            card = AgentCard(name="Ace", supported_interfaces=[
                AgentInterface(url=self._url, protocol_binding="JSONRPC", protocol_version="1.0")])
            self._sdk = await create_client(card, client_config=ClientConfig(httpx_client=self._http, streaming=False))
        request = SendMessageRequest(message=new_message([new_text_part(text)], role=Role.ROLE_USER))
        call = ClientCallContext(service_parameters={"Authorization": f"Bearer {token}"}, timeout=CHAT_TIMEOUT)
        reply = Reply("", [])
        self._hop.clear()
        try:
            async for chunk in self._sdk.send_message(request, context=call):
                if chunk.WhichOneof("payload") == "message":
                    reply.text = get_message_text(chunk.message)
                    reply.trace = next((d["trace"] for d in get_data_parts(chunk.message.parts) if "trace" in d), [])
        except Exception as e:      # the SDK keeps a text for an HTTP error: the status is what the hook saw
            reason = f"HTTP {self._hop.status}: {self._hop.message}" if self._hop.status else type(e).__name__
            raise PlatformError(f"Ace did not answer through the A2A proxy ({reason})", self._hop.status) from e
        return reply

    async def aclose(self) -> None:
        await self._http.aclose()


# --- The bank's tools, over MCP --------------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolReply:
    outcome: str                     # ok, denied, unauthorized, rate_limited, or error: the tool itself refused
    status: int | None
    detail: str                      # the gateway's message, or what the tool returned


VERDICTS = {401: "unauthorized", 403: "denied", 429: "rate_limited"}      # the gateway's answers about the caller


class Tools:
    """The MCP client of the bank's tools through the gateway, with the token of a person: what a customer's own app
    would do, with no agent in between."""

    def __init__(self, settings: Settings, tokens: Tokens, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._url, self._tokens, self._transport = settings.mcp_url, tokens, transport

    @contextlib.asynccontextmanager
    async def _session(self, token: str, hop: Hop) -> AsyncIterator[Client]:
        http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT},
                                  timeout=httpx2.Timeout(30.0), event_hooks={"response": [hop]},
                                  transport=self._transport)
        async with http, Client(streamable_http_client(self._url, http_client=http)) as client:
            yield client

    async def names(self, persona: str) -> list[str]:
        """The tools the proxy lists for this person (tools/list). A dead token is replaced once."""
        try:
            return await self._names(await self._tokens.get(persona))
        except PlatformError as e:
            if e.status != 401:
                raise
            self._tokens.forget(persona)
            return await self._names(await self._tokens.get(persona))

    async def _names(self, token: str) -> list[str]:
        hop = Hop()
        try:
            async with self._session(token, hop) as client:
                return [tool.name for tool in (await client.list_tools()).tools]
        except Exception as e:
            raise unavailable(hop, leaf(e)) from e

    async def call(self, persona: str, tool: str, arguments: dict[str, Any]) -> ToolReply:
        """tools/call as this person. A dead token is replaced once."""
        reply = await self.call_with(await self._tokens.get(persona), tool, arguments)
        if reply.outcome == "unauthorized":
            self._tokens.forget(persona)
            reply = await self.call_with(await self._tokens.get(persona), tool, arguments)
        return reply

    async def call_with(self, token: str, tool: str, arguments: dict[str, Any]) -> ToolReply:
        hop = Hop()
        try:
            async with self._session(token, hop) as client:
                result = await client.call_tool(tool, arguments)
        except Exception as e:
            error = leaf(e)
            if hop.status in VERDICTS:
                return ToolReply(VERDICTS[hop.status], hop.status, hop.message)
            if isinstance(error, MCPError) and hop.status == 200:      # the server's own refusal, as JSON-RPC
                return ToolReply("error", 200, error.message)
            raise unavailable(hop, error) from e
        text = result.content[0].text if result.content else ""
        if result.is_error:
            return ToolReply("error", 200, text)
        return ToolReply("ok", 200, text[:200])


def unavailable(hop: Hop, error: BaseException) -> PlatformError:
    reason = f"HTTP {hop.status}: {hop.message}" if hop.status else f"{type(error).__name__}: {error}"
    return PlatformError(f"the MCP proxy did not answer ({reason})", hop.status)


# --- A model, over the OpenAI API ------------------------------------------------------------------------------

@dataclass(frozen=True)
class Rate:
    """What a rate-limit header triplet says: the limit, what is left of it, and in how many seconds it is over."""
    limit: float | None = None
    remaining: float | None = None
    seconds_left: float | None = None


def rate_of(headers: Mapping[str, str], prefix: str, scale: float = 1.0) -> Rate:
    """`prefix` is x-token-rate-limit or x-cost-rate-limit; the cost headers count millionths of a dollar."""
    def number(suffix: str) -> float | None:
        try:
            return float(headers[f"{prefix}-{suffix}"])
        except (KeyError, ValueError):
            return None
    limit, remaining, reset = number("limit"), number("remaining"), number("reset")
    return Rate(None if limit is None else limit * scale, None if remaining is None else remaining * scale,
                None if reset is None else max(reset / 1000 - time.time(), 0.0))     # epoch milliseconds


@dataclass(frozen=True)
class Completion:
    status: int
    text: str                        # the answer, or the gateway's message when the status is not 200
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False             # the gateway took it from its semantic cache: no model call, no tokens
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class Llm:
    """An OpenAI-compatible endpoint of the gateway and the API key of one consumer of it."""

    def __init__(self, base_url: str, key: str, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        # The SDK sends the key as Authorization: Bearer, which an LLM proxy plan and a workspace plan both read.
        # max_retries=0: the SDK would retry a 429 or a 5xx and hide it.
        self._client = AsyncOpenAI(
            base_url=base_url, api_key=key, timeout=TIMEOUT, max_retries=0,
            default_headers={"User-Agent": USER_AGENT},
            http_client=httpx2.AsyncClient(transport=transport) if transport else None)

    async def models(self) -> int:
        """The status of GET /models: free, and it needs the API and the key to be live."""
        try:
            return (await self._client.models.with_raw_response.list()).status_code
        except openai.APIStatusError as e:
            return e.status_code
        except openai.APIError as e:
            raise PlatformError(f"the gateway does not answer ({type(e).__name__})") from e

    async def chat(self, model: str, content: str, max_tokens: int = 150) -> Completion:
        try:
            # reasoning_effort none: qwen3 thinks by default, and with a small max_tokens its answer would stay
            # in the reasoning and the content come back empty
            raw = await self._client.chat.completions.with_raw_response.create(
                model=model, messages=[{"role": "user", "content": content}], max_tokens=max_tokens, temperature=0.2,
                reasoning_effort="none")
            answer = raw.parse()
        except openai.APIStatusError as e:      # a policy said no (400, 403), a limit (429), the key (401)
            return Completion(e.status_code, message_of(e.body, f"HTTP {e.status_code}"),
                              headers=dict(e.response.headers))
        except openai.APIError as e:
            raise PlatformError(f"the gateway does not answer ({type(e).__name__})") from e
        usage = answer.usage
        text = (answer.choices[0].message.content or "") if answer.choices else ""
        return Completion(raw.status_code, text, answer.model or model, usage.prompt_tokens if usage else 0,
                          usage.completion_tokens if usage else 0, answer.id == CACHE_ANSWER_ID,
                          dict(raw.headers))

    async def aclose(self) -> None:
        await self._client.close()


class Teams:
    """Chats of the users of the AI workspace, each with the key Gravitee generated for them."""

    MODEL = "smart"      # an alias of the workspace: its router moves a user to the small model as the budget goes

    def __init__(self, workspace: Workspace, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._workspace, self._transport = workspace, transport
        self._llms: dict[str, Llm] = {}

    async def _llm(self, team: str) -> Llm:
        if not self._workspace.loaded:
            await self.reload()
        if team not in self._llms:
            self._llms[team] = Llm(self._workspace.entrypoint, self._workspace.key(team), self._transport)
        return self._llms[team]

    async def reachable(self, team: str) -> None:
        status = await (await self._llm(team)).models()
        if status not in (200, 429):
            raise PlatformError(f"the AI workspace answered HTTP {status} to {team}'s key", status)

    async def chat(self, team: str, content: str, max_tokens: int) -> Completion:
        """A 401 means the key changed: the keys are read again from Gamma and the call is made once more."""
        reply = await (await self._llm(team)).chat(self.MODEL, content, max_tokens=max_tokens)
        if reply.status == 401:
            await self.reload()
            reply = await (await self._llm(team)).chat(self.MODEL, content, max_tokens=max_tokens)
        return reply

    async def reload(self, deployed: bool = False) -> None:
        """Reads the keys again from Gamma. `deployed` is for a first start: it waits for the workspace to be live."""
        await self._workspace.load(deployed)
        stale, self._llms = list(self._llms.values()), {}
        for llm in stale:
            await llm.aclose()

    async def aclose(self) -> None:
        await self._workspace.aclose()
        for llm in self._llms.values():
            await llm.aclose()
