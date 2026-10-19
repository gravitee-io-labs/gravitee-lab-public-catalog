"""What keeps another web page, or another name for this machine, from using the app.

- The Host must be one this app is meant to be reached by (a page on a hostile name that points at localhost, the
  DNS rebinding trick, sends its own name).
- A request that changes something, or that asks the app for anything (every /api route: some call the platform), must come
  from this app's own page: its Origin is this Host. A web page elsewhere can make a visitor's browser send a GET, and the app
  must not do the work for it.
- The page's own calls to an /api route carry `X-Requested-With: acme-bank`, and a GET without it is refused: a browser lets a
  page elsewhere send a GET (an image, a link, a prefetch) but not add a header like that to it, so the check holds in a browser
  that sends no `Sec-Fetch-Site` (before Chrome 76, Firefox 90, Safari 16.4). HEAD is asked the same: the framework runs a GET route
  for it. Only /api/evidence is exempt: a link of the evidence opens it, and a link cannot add a header.
- A sign-in is started by this page only (/login): a request from another site cannot make the browser open Access Management's login page for it.
- Every answer carries headers that keep the page from loading, or being framed by anything but the Lab UI. The pages of a sign-in, which run in a window of
  their own and are framed by nobody, get a policy that allows a script and a stylesheet of this app and nothing else.
"""
import re
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
HOST = re.compile(r"^(\[[^\]]+\]|[^:]+)(?::\d+)?$")
LAB_UI = "http://localhost:9000 http://127.0.0.1:9000"       # the Lab UI shows the app next to the guide: no other page may frame it
POLICY = f"default-src 'self'; img-src 'self' data:; frame-ancestors {LAB_UI}; base-uri 'none'; form-action 'self'"
# What the window of a sign-in is served with: it is framed by nobody and loads nothing but its own script and stylesheet
SIGN_IN_POLICY = "default-src 'none'; script-src 'self'; style-src 'self'; img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
SIGN_IN_PATHS = ("/login", "/callback", "/sign-in-done.html")
STARTS = "/login"            # a sign-in begins here: only a click of this page may start one
PAGE_HEADER, PAGE_VALUE = "x-requested-with", "acme-bank"
LINKED = ("/api/evidence",)          # opened by following a link, which cannot carry a header


def host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    found = HOST.match(host)
    return bool(found) and found.group(1).lower() in allowed


def asked_by_the_page(method: str, path: str, headers: Headers) -> bool:
    """Whether a GET of an /api route carries the header the page adds to its own calls (the other requests are not asked)."""
    if method not in ("GET", "HEAD") or not path.startswith("/api/") or path in LINKED:      # HEAD runs a GET route's work too
        return True
    return headers.get(PAGE_HEADER) == PAGE_VALUE


def from_this_page(headers: Headers) -> bool:
    """Browsers send an Origin with every request that changes something, and Sec-Fetch-Site with every request; a tool such as
    curl sends neither. A person typing the address of a route (Sec-Fetch-Site: none) is not another web page."""
    origin = headers.get("origin")
    if origin is not None:
        return urlsplit(origin).netloc == headers.get("host", "")
    return headers.get("sec-fetch-site", "same-origin") in ("same-origin", "none")


class Guard:
    def __init__(self, app, allowed_hosts: tuple[str, ...]):
        self.app = app
        self.allowed = tuple(h.lower() for h in allowed_hosts)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        if scope["path"] != "/health":            # the health check calls by the container's own name
            if not host_allowed(headers.get("host", ""), self.allowed):
                return await self._refuse(scope, receive, send, "This host name is not in ALLOWED_HOSTS", 421)
            asks = scope["method"] not in SAFE_METHODS or scope["path"].startswith("/api/") or scope["path"] == STARTS
            if asks and not (from_this_page(headers) and asked_by_the_page(scope["method"], scope["path"], headers)):
                return await self._refuse(scope, receive, send, "The request does not come from this page", 403)
        await self.app(scope, receive, self._hardened(scope, send))

    @staticmethod
    async def _refuse(scope, receive, send, message: str, status: int):
        await JSONResponse({"error": message}, status_code=status)(scope, receive, send)

    @staticmethod
    def _hardened(scope, send):
        in_sign_in = scope["path"] in SIGN_IN_PATHS
        no_cache = "no-store" if scope["path"].startswith("/api/") or in_sign_in else "no-cache"

        async def wrapped(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Content-Security-Policy"] = SIGN_IN_POLICY if in_sign_in else POLICY
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
                headers.setdefault("Cache-Control", no_cache)
            await send(message)
        return wrapped
