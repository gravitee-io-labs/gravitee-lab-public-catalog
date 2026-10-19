"""Plain JSON-RPC calls to an MCP endpoint, for the few the page makes itself (`tools/list`, `tools/call`).

The bank's MCP server is stateless: it answers a call without a session and without `initialize`, behind the
gateway too, so no MCP client library is needed here.
"""
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from upstream import GATEWAY_REQUEST, GATEWAY_TRANSACTION, UpstreamError, elapsed_ms, json_body

HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@dataclass
class McpReply:
    status: int
    body: Any
    ms: int
    transaction_id: str | None
    request_id: str | None


def _json_rpc_body(response: httpx.Response) -> Any:
    """A server may answer with an event stream: the first `data:` line is the JSON-RPC message."""
    if "event-stream" in response.headers.get("content-type", ""):
        line = next((text[5:].strip() for text in response.text.splitlines() if text.startswith("data:")), "")
        try:
            return json.loads(line)
        except ValueError:
            return line
    return json_body(response)


async def call(http: httpx.AsyncClient, url: str, method: str, params: dict, token: str | None = None) -> McpReply:
    headers = {**HEADERS, **({"Authorization": f"Bearer {token}"} if token else {})}
    started = time.monotonic()
    try:
        message = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        response = await http.post(url, headers=headers, json=message)
    except httpx.HTTPError as e:
        raise UpstreamError("The bank's tools are not answering") from e
    return McpReply(response.status_code, _json_rpc_body(response), elapsed_ms(started),
                    response.headers.get(GATEWAY_TRANSACTION), response.headers.get(GATEWAY_REQUEST))


async def list_tools(http: httpx.AsyncClient, url: str, token: str | None = None) -> list[str]:
    reply = await call(http, url, "tools/list", {}, token)
    tools = reply.body.get("result", {}).get("tools") if isinstance(reply.body, dict) else None
    if reply.status != 200 or not isinstance(tools, list):
        raise UpstreamError(f"The bank's tools answered HTTP {reply.status} to the list of tools")
    return [tool["name"] for tool in tools if isinstance(tool, dict) and "name" in tool]
