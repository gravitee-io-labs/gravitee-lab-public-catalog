"""Send money: the human path. The signed-in user calls `transfer_funds` through the MCP proxy with their own token,
no agent in between, so the same amount can be permitted here and denied when Ace asks for it."""
from typing import Any

import httpx

import hops
import mcp_rpc
from hops import clip
from people import Persona
from upstream import message_of

TOOL = "transfer_funds"


class BadTransfer(ValueError):
    """The request is not a transfer at all: the page showed no form for it."""


def parse(body: dict) -> dict[str, Any]:
    """The arguments of the transfer. The amount is passed on as typed, zero and negative included: whether it is
    allowed is the policies' business, and the page shows what they answer."""
    arguments: dict[str, Any] = {}
    for key in ("from_account", "to_account"):
        value = body.get(key)
        if not isinstance(value, str) or not 0 < len(value.strip()) <= 20:
            raise BadTransfer(f"{key} is missing")
        arguments[key] = value.strip()
    amount = body.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise BadTransfer("amount must be a number")
    arguments["amount"] = amount
    reference = body.get("reference")
    if isinstance(reference, str) and reference.strip():
        arguments["reference"] = reference.strip()[:60]
    return arguments


def _summary(result: dict) -> str:
    data = result.get("structuredContent")
    if isinstance(data, dict):
        return clip(", ".join(f"{key} {value}" for key, value in data.items() if not isinstance(value, (dict, list))))
    content = result.get("content")
    return clip(content[0].get("text") if isinstance(content, list) and content else "")


def _outcome(reply: mcp_rpc.McpReply) -> tuple[str, str]:
    """(outcome of the hop, what to say about it)"""
    body = reply.body
    if reply.status == 200 and isinstance(body, dict) and isinstance(body.get("result"), dict):
        result = body["result"]
        return ("error" if result.get("isError") else "ok"), _summary(result)
    outcome = {401: "unauthorized", 403: "denied", 429: "rate_limited"}.get(reply.status, "error")
    return outcome, message_of(body) or f"HTTP {reply.status}"


def _request_id(reply: mcp_rpc.McpReply) -> str | None:
    """A denial carries the request id the Decisions page filters on; otherwise the gateway's own header."""
    error = reply.body.get("error") if isinstance(reply.body, dict) else None
    data = error.get("data") if isinstance(error, dict) else None
    return (data.get("requestId") if isinstance(data, dict) else None) or reply.request_id


async def send(http: httpx.AsyncClient, url: str, token: str | None, arguments: dict, person: Persona | None, *, gateway: bool) -> dict:
    """The person's call of the tool. `gateway` False: the bank's MCP server is called directly, with nothing in front of it. No `token` through the gateway is a call
    of nobody (`person` None), which the MCP proxy's OAuth2 plan refuses. The answer is the hop of that call."""
    reply = await mcp_rpc.call(http, url, "tools/call", {"name": TOOL, "arguments": arguments}, token)
    outcome, detail = _outcome(reply)
    if reply.status == 401 and gateway and token is None:
        detail = hops.NO_TOKEN
    hop = hops.payment(person, TOOL, arguments, outcome, detail, gateway=gateway, status=reply.status, ms=reply.ms,
                       transaction_id=reply.transaction_id, request_id=_request_id(reply))
    return {**hop, "protected": gateway}
