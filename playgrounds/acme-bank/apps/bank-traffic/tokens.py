"""The sign-in of the cast: a password grant at AM, with the generator's own application. The bank's web app has none: its
people sign in at the login page of AM."""
import time
from typing import Callable

import httpx

from cast import USERNAMES
from settings import Settings
from wire import USER_AGENT, PlatformError, message_of

EARLY = 60        # seconds: a token is replaced a minute before it expires, so no call carries a dead one
LIFETIME = 300    # seconds, when AM does not say
SCOPE = "openid profile email"


class Tokens:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._settings, self._clock = settings, clock
        self._http = httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=30, transport=transport)
        self._cache: dict[str, tuple[str, float]] = {}

    async def get(self, persona: str) -> str:
        cached = self._cache.get(persona)
        if cached and self._clock() < cached[1]:
            return cached[0]
        token, lifetime = await self._sign_in(persona)
        self._cache[persona] = (token, self._clock() + max(lifetime - EARLY, 0))
        return token

    def forget(self, persona: str) -> None:
        """The gateway refused this token (revoked, or AM restarted): the next call signs in again."""
        self._cache.pop(persona, None)

    async def _sign_in(self, persona: str) -> tuple[str, float]:
        settings = self._settings
        try:
            answer = await self._http.post(
                settings.am_token_url, auth=(settings.client_id, settings.client_secret),
                data={"grant_type": "password", "username": USERNAMES[persona], "password": settings.password,
                      "scope": SCOPE})
        except httpx.HTTPError as e:
            raise PlatformError(f"AM does not answer ({type(e).__name__})") from e
        if answer.status_code != 200:
            raise PlatformError(f"AM refused to sign {persona} in: HTTP {answer.status_code} "
                                f"{message_of(answer.text)}", answer.status_code)
        try:
            body = answer.json()
            return body["access_token"], float(body.get("expires_in", LIFETIME))
        except (ValueError, KeyError, TypeError) as e:
            raise PlatformError(f"AM answered {persona}'s sign-in without an access token") from e

    async def aclose(self) -> None:
        await self._http.aclose()
