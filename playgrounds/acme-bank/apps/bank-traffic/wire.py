"""What the platform answers, as the rest of the generator needs it: a failure with its status, and the last answer
the SDKs would otherwise hide."""
import json
from typing import Any

USER_AGENT = "acme-bank-traffic"
BODY_LIMIT = 300


class PlatformError(Exception):
    """The platform did not answer the way a scenario needs: still starting, restarting, or refusing a sign-in.
    It is not a verdict on the policies, so it never counts as a failed expectation."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def message_of(body: Any, default: str = "") -> str:
    """The sentence of an error body: {"message"} from a gateway policy, {"error": {"message"}} from a provider or a
    JSON-RPC error, {"error_description"} from AM. Plain text is returned as it is, shortened."""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return body.strip()[:BODY_LIMIT] or default
    if isinstance(body, dict):
        error = body.get("error")
        for candidate in (body.get("message"), body.get("error_description"),
                          error.get("message") if isinstance(error, dict) else error):
            if isinstance(candidate, str) and candidate:
                return candidate
    return default


class Hop:
    """The last answer of the gateway to a request of one SDK client. The MCP and A2A clients turn any answer that is
    not a success into an exception that has lost the status and the message, so a response hook on their HTTP client
    keeps both. The same class serves httpx and httpx2: it only reads what both have. Only POSTs count: every
    JSON-RPC request is one, and the MCP client may also open a GET stream that says nothing about the call."""

    def __init__(self) -> None:
        self.status: int | None = None
        self.message = ""

    def clear(self) -> None:
        self.status, self.message = None, ""

    async def __call__(self, response: Any) -> None:
        if response.request.method != "POST":
            return
        self.status, self.message = response.status_code, ""
        if response.status_code >= 400:
            await response.aread()
            self.message = message_of(response.text, f"HTTP {response.status_code}")
