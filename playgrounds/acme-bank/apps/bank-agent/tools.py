"""The bank's tools over MCP: one Streamable HTTP session per chat, with the token the tools are called with.

Behind the gateway the MCP proxy introspects that token, shows only the tools its role may use (`tools/list`) and
decides every `tools/call`. A refusal is an HTTP answer, not a JSON-RPC one: the response hook of
`gateway.HopRecorder` is where its status, message and transaction id are read.
"""
import contextlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx2
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client

from gateway import TRANSACTION_HEADER, Hop, HopRecorder, wait_seconds
from steps import elapsed_ms

DETAIL_LIMIT = 200         # characters of a tool's answer kept in the trace
TIMEOUT = 35               # seconds: the gateway answers 504 after 30, so its answer is the one that is read
EXPIRED = "Your session has expired. Sign in again."
TIMED_OUT = "The bank's service did not answer in time."
UNREACHABLE = "The bank's service is not reachable."
INVALID_ARGUMENTS = json.dumps({"error": "invalid_arguments", "message": "The arguments must be a JSON object."})


@dataclass(frozen=True)
class ToolResult:
    outcome: str                # ok | denied | rate_limited | error
    content: str                # what the model reads
    detail: str                 # what the trace shows
    ms: int
    status: int | None = None
    ids: dict[str, str | None] = field(default_factory=dict)     # transaction_id, request_id


@contextlib.asynccontextmanager
async def open_session(url: str, token: str | None, recorder: HopRecorder,
                       transport: httpx2.AsyncBaseTransport | None = None,
                       transaction_id: str | None = None) -> AsyncIterator[Client]:
    """A client of the MCP server that sends the token when there is one, and the transaction id of the turn so that the
    gateway files every call of the turn under it. `transport` is for tests."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if transaction_id:
        headers[TRANSACTION_HEADER] = transaction_id
    http = httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(TIMEOUT), transport=transport,
                              event_hooks={"response": [recorder]})
    async with http, Client(streamable_http_client(url, http_client=http)) as client:
        yield client


async def list_tools(client: Client, recorder: HopRecorder) -> tuple[list[dict[str, Any]], ToolResult]:
    """The tools this user may use (the MCP proxy filters them by role) as OpenAI tools, and the hop that listed them."""
    recorder.reset()
    started = time.monotonic()
    tools = openai_tools((await client.list_tools()).tools)
    return tools, stamped("ok", "", f"{len(tools)} tools", elapsed_ms(started), recorder.last)


def openai_tools(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    """MCP tools as OpenAI function tools. The input schema is JSON Schema already: it goes as it is."""
    return [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                              "parameters": t.input_schema}} for t in mcp_tools]


def parse_arguments(raw: str) -> dict[str, Any] | None:
    """The arguments of a tool call, or None when the model did not write a JSON object."""
    try:
        arguments = json.loads(raw)
    except ValueError:
        return None
    return arguments if isinstance(arguments, dict) else None


async def call_tool(client: Client, recorder: HopRecorder, name: str, arguments: dict[str, Any]) -> ToolResult:
    recorder.reset()
    started = time.monotonic()
    try:
        result = await client.call_tool(name, arguments)
    except MCPError as e:               # the gateway refused, or the server failed: the hook saw the HTTP answer
        return refused(e, recorder.last, elapsed_ms(started))
    text = "\n".join(block.text for block in result.content if getattr(block, "text", None))
    # is_error: the tool itself said no ("Insufficient funds ...")
    return stamped("error" if result.is_error else "ok", text, " ".join(text.split())[:DETAIL_LIMIT],
                   elapsed_ms(started), recorder.last)


def refused(error: MCPError, hop: Hop | None, ms: int) -> ToolResult:
    """What the gateway answered to a tool call, as the model and the trace should read it."""
    if hop is None or hop.status < 400:             # a JSON-RPC error inside a 200 answer, or no answer at all
        return refusal("error", "tool_error", error.message, ms, hop)
    if hop.status == 403:
        return refusal("denied", "forbidden", hop.message or "Not allowed.", ms, hop)
    if hop.status == 429:
        return refusal("rate_limited", "rate_limited", hop.message or "Too many requests.", ms, hop,
                       retry_after_seconds=wait_seconds(hop.headers))
    if hop.status == 401:
        return refusal("error", "unauthorized", EXPIRED, ms, hop)
    if hop.status == 504:
        return refusal("error", "timeout", TIMED_OUT, ms, hop)
    return refusal("error", f"gateway_{hop.status}", hop.message or f"HTTP {hop.status}", ms, hop)


def refusal(outcome: str, code: str, message: str, ms: int, hop: Hop | None, **more: Any) -> ToolResult:
    return stamped(outcome, json.dumps({"error": code, "message": message, **more}), message, ms, hop)


def stamped(outcome: str, content: str, detail: str, ms: int, hop: Hop | None) -> ToolResult:
    """A result with the status and the transaction of the gateway answer it came from."""
    if hop is None:
        return ToolResult(outcome, content, detail, ms)
    return ToolResult(outcome, content, detail, ms, hop.status, hop.ids)
