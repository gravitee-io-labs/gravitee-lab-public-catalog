"""What keeps another web page, or another name for this machine, from using the app.

- The Host must be one the app is meant to be reached by: a page on a hostile name that points at this machine (the DNS
  rebinding trick) sends its own name. /health is exempt, because the container's health check calls it by its own name.
- A POST must say it is JSON, or be a webhook of the gateway, which says nothing. A page on another site can send a POST
  without the browser's leave only when its body is plain text or a form.
- A POST that comes from a browser must come from the app's own page: its Origin is this Host. The gateway and curl send no Origin.
- Every answer carries headers that keep the page from loading anything from elsewhere and from being framed by anything
  but the Lab UI.
"""
import re
from urllib.parse import urlsplit

HOST = re.compile(r"^(\[[^\]]+\]|[^:]+)(?::\d+)?$")
JSON = re.compile(r"^application/(?:[\w.+-]+\+)?json\s*(?:;|$)", re.IGNORECASE)
LAB_UI = "http://localhost:9000 http://127.0.0.1:9000"       # the Lab UI shows the page next to the guide: no other page may frame it
POLICY = f"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors {LAB_UI}; base-uri 'none'; form-action 'none'"


def host_allowed(host: str, allowed: tuple[str, ...]) -> bool:
    found = HOST.match(host)
    return bool(found) and found.group(1).lower() in allowed


def is_json(content_type: str | None, may_be_missing: bool = False) -> bool:
    if content_type is None or not content_type.strip():
        return may_be_missing
    return bool(JSON.match(content_type))


def from_this_page(origin: str | None, fetch_site: str | None, host: str) -> bool:
    """Browsers send an Origin with every POST, and Sec-Fetch-Site with every request; the gateway and curl send neither."""
    if origin is not None:
        return urlsplit(origin).netloc == host
    return fetch_site in (None, "same-origin", "none")


def hardened() -> dict[str, str]:
    return {"Content-Security-Policy": POLICY, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}
