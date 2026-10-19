"""The sign-ins that are on their way: the authorization code flow with PKCE, from the page's click to the return of Access Management.

A sign-in starts at /login, which makes a `state` (what brings the browser back to this very sign-in) and a `code_verifier` (what proves that the one who asks for
the tokens is the one who started it). The verifier never leaves this process: Access Management gets its S256 challenge, and sees the verifier only when the
code is exchanged, from here, on the back channel. A sign-in is of one browser session (the cookie that started it must be the cookie that comes back), is taken
once (a `state` that came back is gone, whatever it was worth), lives ten minutes at most, and there are only so many at a time.
"""
import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Callable

TTL = 600            # seconds: the time to read a login page and type a password
LIMIT = 100          # sign-ins on their way, all browsers together
PER_SESSION = 4      # and one browser's own: another click on a persona is another sign-in, the oldest of the browser goes


def challenge(verifier: str) -> str:
    """The S256 code challenge of a verifier: base64url, without padding, of its SHA-256 (RFC 7636)."""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class Pending:
    persona: str            # who the page asked to sign in
    verifier: str
    sid: str                # the session of the browser that started it
    redirect_uri: str       # sent to Access Management, and sent again with the code: they must be the same
    started: float


class SignIns:
    def __init__(self, ttl: float = TTL, limit: int = LIMIT, per_session: int = PER_SESSION, clock: Callable[[], float] = time.time):
        self._items: dict[str, Pending] = {}
        self.ttl, self.limit, self.per_session, self.clock = ttl, limit, per_session, clock

    def begin(self, sid: str, persona: str, redirect_uri: str) -> tuple[str, str]:
        """A sign-in for this person in this browser session: the `state` that comes back and the challenge Access Management is given."""
        self._expire()
        mine = [state for state, pending in self._items.items() if pending.sid == sid]
        for state in mine[: max(0, len(mine) - self.per_session + 1)]:
            del self._items[state]
        while len(self._items) >= self.limit:
            del self._items[next(iter(self._items))]
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)       # 43 and 86 characters of the unreserved alphabet: RFC 7636 asks for 43 to 128 for a verifier
        self._items[state] = Pending(persona, verifier, sid, redirect_uri, self.clock())
        return state, challenge(verifier)

    def take(self, state: str) -> Pending | None:
        """The sign-in of a `state`, once: it is taken out when asked for, whether it is found and valid or not."""
        pending = self._items.pop(state, None)
        return pending if pending is not None and self.clock() - pending.started <= self.ttl else None

    def _expire(self) -> None:
        for state in [s for s, p in self._items.items() if self.clock() - p.started > self.ttl]:
            del self._items[state]
