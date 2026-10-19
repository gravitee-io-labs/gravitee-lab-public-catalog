"""What keeps another web page, or another name for this machine, from calling Ace.

- A call that changes something (a POST) must say it is JSON. A page on another site can send a POST without asking
  the browser's leave only when its body is plain text or a form, so a JSON-only Ace is out of its reach: the
  browser would first ask a question (the preflight) that Ace never answers with a permission.
- The Host must be one Ace is meant to be reached by: a page on a hostile name that points at this machine (the DNS
  rebinding trick) sends its own name. The health check is exempt: the container calls it by its own name.
"""
import re

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

HOST = re.compile(r"^(\[[^\]]+\]|[^:]+)(?::\d+)?$")
JSON = re.compile(r"^application/(?:[\w.+-]+\+)?json\s*(?:;|$)", re.IGNORECASE)


def host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    found = HOST.match(host)
    return bool(found) and found.group(1).lower() in allowed


class Guard:
    def __init__(self, app: ASGIApp, allowed_hosts: tuple[str, ...]) -> None:
        self.app = app
        self.allowed = tuple(h.lower() for h in allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] != "/health":
            headers = Headers(scope=scope)
            if not host_allowed(headers.get("host", ""), self.allowed):
                return await refuse(scope, receive, send, "This host name is not in ALLOWED_HOSTS", 421)
            if scope["method"] == "POST" and not JSON.match(headers.get("content-type", "")):
                return await refuse(scope, receive, send, "A call must be JSON: Content-Type application/json", 415)
        await self.app(scope, receive, send)


async def refuse(scope: Scope, receive: Receive, send: Send, message: str, status: int) -> None:
    await JSONResponse({"error": message}, status_code=status)(scope, receive, send)
