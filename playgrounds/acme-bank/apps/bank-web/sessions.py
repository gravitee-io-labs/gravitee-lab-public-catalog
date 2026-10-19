"""Server-side sessions: the browser only holds an opaque id in an HttpOnly cookie, the tokens stay here.

A session holds the tokens of every person who signed in from that browser (each signed in once, at Access Management's own page), and who asks
now. Choosing a person who is already signed in is instant; choosing one who is not is a sign-in.
"""
import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from people import Persona


@dataclass
class Tokens:
    access_token: str
    refresh_token: str | None
    expires_at: float


class NotSignedIn(Exception):
    """Nobody is signed in for what was asked: `persona` is the one who has to sign in, when it is somebody's."""

    def __init__(self, message: str, persona: Persona | None = None):
        super().__init__(message)
        self.message, self.persona = message, persona


@dataclass
class Session:
    started: float
    persona: Persona | None = None                               # who asks now
    signed: dict[str, Tokens] = field(default_factory=dict)      # the tokens of each person signed in from this browser, by persona id
    contexts: dict[str, str] = field(default_factory=dict)       # A2A conversation id, one per gateway mode
    delegated_claims: dict[str, Any] | None = None               # the token Ace got for the last question
    renewing: asyncio.Lock = field(default_factory=asyncio.Lock)  # one renewal at a time: a refresh token that is used twice is one Access Management may refuse the second time

    def choose(self, persona: Persona) -> None:
        """Another person asks: the conversation starts again, nothing of the one before stays."""
        if self.persona is None or self.persona.id != persona.id:
            self.persona = persona
            self.contexts.clear()
            self.delegated_claims = None

    def sign_in(self, persona: Persona, tokens: Tokens) -> None:
        self.signed[persona.id] = tokens
        self.choose(persona)

    def forget(self, persona: Persona) -> None:
        """The tokens of a person are of no use (expired, refused): they are dropped, and nobody is asking as that person."""
        self.signed.pop(persona.id, None)
        if self.persona is not None and self.persona.id == persona.id:
            self.persona = None
            self.contexts.clear()
            self.delegated_claims = None

    @property
    def tokens(self) -> Tokens | None:
        """The tokens of the person who asks now."""
        return self.signed.get(self.persona.id) if self.persona else None


class Sessions:
    def __init__(self, ttl: float = 8 * 3600, limit: int = 200, clock: Callable[[], float] = time.time):
        self._items: dict[str, Session] = {}
        self.ttl, self.limit, self.clock = ttl, limit, clock

    def open(self) -> tuple[str, Session]:
        """A session for a browser that has none. Only so many at a time: where it is full, one that holds no token goes first (a flood of visits signs nobody out),
        and the oldest of the rest where all of them do."""
        self._expire()
        while len(self._items) >= self.limit:
            self._items.pop(next((sid for sid, held in self._items.items() if not held.signed), next(iter(self._items))))
        sid = secrets.token_urlsafe(32)
        self._items[sid] = Session(self.clock())
        return sid, self._items[sid]

    def get(self, sid: str) -> Session | None:
        session = self._items.get(sid)
        if session is not None and self.clock() - session.started > self.ttl:
            self._items.pop(sid)
            return None
        return session

    def close(self, sid: str) -> None:
        self._items.pop(sid, None)

    def forget_conversations(self) -> None:
        """A reset starts every conversation again: Ace answers each question as a first one."""
        for session in self._items.values():
            session.contexts.clear()

    def _expire(self) -> None:
        for sid in [s for s, v in self._items.items() if self.clock() - v.started > self.ttl]:
            self._items.pop(sid)
