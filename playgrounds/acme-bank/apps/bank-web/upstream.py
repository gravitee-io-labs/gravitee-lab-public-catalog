"""What bank-web depends on: the HTTP clients, the errors it shows, and what it keeps of the gateway's answers.

Every call to another service goes through one of the clients of `Clients`, so a test swaps all of them for fakes.
"""
import contextlib
import contextvars
import re
import time
from dataclasses import dataclass
from typing import Any, Iterator

import httpx

GATEWAY_TRANSACTION = "x-gravitee-transaction-id"
GATEWAY_REQUEST = "x-gravitee-request-id"
ID = re.compile(r"[A-Za-z0-9_-]{8,64}")          # a request id, an event id, an API id: matched whole (fullmatch): `$` would let a newline follow

_seen: contextvars.ContextVar = contextvars.ContextVar("seen", default=None)


class UpstreamError(Exception):
    """Something bank-web depends on answered badly. The message is meant for the page."""

    def __init__(self, message: str, status: int = 502, upstream: int | None = None, detail: str = ""):
        super().__init__(message)
        # `upstream`: the status the service itself gave; `detail`: what it said, for the log and never for the page
        self.message, self.status, self.upstream, self.detail = message, status, upstream, detail
        self.rows: list[dict] = []        # the hops of the call that failed, where the gateway answered it: Behind the answer draws them


async def _remember(response: httpx.Response) -> None:
    seen = _seen.get()
    if seen is None:
        return
    seen.update(status=response.status_code, transaction_id=response.headers.get(GATEWAY_TRANSACTION),
                request_id=response.headers.get(GATEWAY_REQUEST))
    if response.status_code >= 400:
        await response.aread()
        seen["body"] = response.text[:500]


@contextlib.contextmanager
def recording() -> Iterator[dict]:
    """The A2A SDK hides the status and headers of its HTTP answers: while this is open, the last one is kept in
    the dict. A context variable keeps two chats at once from reading each other's answer."""
    seen: dict = {}
    token = _seen.set(seen)
    try:
        yield seen
    finally:
        _seen.reset(token)


@dataclass
class Clients:
    am: httpx.AsyncClient
    a2a: httpx.AsyncClient
    gateway: httpx.AsyncClient
    gamma: httpx.AsyncClient
    internal: httpx.AsyncClient

    def __post_init__(self) -> None:
        self.a2a.event_hooks = {**self.a2a.event_hooks, "response": [_remember]}

    @classmethod
    def live(cls) -> "Clients":
        short = httpx.Timeout(10.0)
        return cls(am=httpx.AsyncClient(timeout=short),
                   a2a=httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=120.0)),
                   gateway=httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=60.0)),
                   gamma=httpx.AsyncClient(timeout=short),
                   internal=httpx.AsyncClient(timeout=short))

    async def aclose(self) -> None:
        for client in {id(c): c for c in (self.am, self.a2a, self.gateway, self.gamma, self.internal)}.values():
            await client.aclose()


def clean(request_id: Any) -> str | None:
    """A request id as the gateway gave it, or None: only what the route of the evidence takes ever makes a link."""
    return request_id if isinstance(request_id, str) and ID.fullmatch(request_id) else None


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def json_body(response: httpx.Response) -> Any:
    """The JSON of an answer, or its text when it is not JSON (a gateway timeout has an empty body)."""
    try:
        return response.json()
    except ValueError:
        return response.text


def message_of(body: Any, default: str = "") -> str:
    """The message of a gateway error: {"message": ...}, a JSON-RPC {"error": {"message": ...}} or plain text."""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or default)
        return str(body.get("message") or error or default)
    return str(body or default)[:300]
