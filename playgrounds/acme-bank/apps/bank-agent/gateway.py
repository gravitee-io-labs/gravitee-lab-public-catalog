"""What an answer of the gateway says: its message, how long to wait, which transaction it belongs to.

The MCP client turns any answer that is not 2xx into MCPError("Server returned an error response") and drops the
status, the body and the headers. A response hook on its HTTP client keeps them.
"""
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping

TRANSACTION_HEADER = "x-gravitee-transaction-id"
TRANSACTION_ID = re.compile(r"[A-Za-z0-9._-]{1,100}")
REQUEST_HEADER = "x-gravitee-request-id"
RESET_HEADERS = ("x-token-rate-limit-reset", "x-rate-limit-reset")    # epoch milliseconds
BODY_LIMIT = 2000


def message_of(body: Any, default: str = "") -> str:
    """The sentence of an error body: {"message"} from a policy, {"error": {"message"}} from a provider or a
    JSON-RPC error, {"error_description"} from AM. Plain text is returned as it is."""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return body.strip()[:200] or default
    if isinstance(body, dict):
        error = body.get("error")
        for candidate in (body.get("message"), body.get("error_description"),
                          error.get("message") if isinstance(error, dict) else error):
            if isinstance(candidate, str) and candidate:
                return candidate
    return default


def wait_seconds(headers: Mapping[str, str]) -> int | None:
    """How long a limit says to wait: Retry-After in seconds, or a reset time in epoch milliseconds."""
    retry_after = headers.get("retry-after", "")
    if retry_after.isdigit():
        return max(1, int(retry_after))
    for name in RESET_HEADERS:
        try:
            reset = float(headers.get(name, ""))
        except ValueError:
            continue
        if reset > 0:
            return max(1, math.ceil(reset / 1000 - time.time()))
    return None


def try_again(wait: int | None) -> str:
    """The end of a limit sentence: " Try again in 7 seconds.", or nothing when the gateway did not say."""
    return "" if wait is None else f" Try again in {wait} second{'s' if wait != 1 else ''}."


def incoming_transaction(headers: Mapping[str, str]) -> str | None:
    """The transaction id the gateway gave the call that reached Ace, when it is a plain token. Ace sends it on its own
    calls to the gateway, which keeps a transaction id it is given: one filter in Logs then shows the whole turn."""
    value = headers.get(TRANSACTION_HEADER, "").strip()
    return value if TRANSACTION_ID.fullmatch(value) else None


def ids_of(headers: Mapping[str, str]) -> dict[str, str | None]:
    """The gateway's identifiers of a request: what Logs and Decisions are searched with."""
    return {"transaction_id": headers.get(TRANSACTION_HEADER), "request_id": headers.get(REQUEST_HEADER)}


@dataclass(frozen=True)
class Hop:
    """One answer of the gateway to a request of the MCP session."""
    status: int
    body: str                     # only for status 400 and above
    headers: Mapping[str, str]

    @property
    def message(self) -> str:
        return message_of(self.body)

    @property
    def ids(self) -> dict[str, str | None]:
        return ids_of(self.headers)


class HopRecorder:
    """Response hook of the MCP session's HTTP client: keeps the last answer to a POST (each JSON-RPC request is one)."""

    def __init__(self) -> None:
        self.last: Hop | None = None

    def reset(self) -> None:
        self.last = None

    async def __call__(self, response: Any) -> None:
        if response.request.method != "POST":
            return
        body = ""
        if response.status_code >= 400:
            await response.aread()
            body = response.text[:BODY_LIMIT]
        self.last = Hop(response.status_code, body, response.headers)
