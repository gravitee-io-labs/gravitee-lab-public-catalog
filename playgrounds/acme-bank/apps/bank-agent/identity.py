"""Who Ace acts for: the claims of the user's token, and the delegated token Access Management issues for it.

A delegated token (RFC 8693) says `sub` = the user and `act.sub` = Ace: the MCP proxy's authorization sees the user,
and the agent they act through. It takes its custom claims from Ace's own application at AM, which defines the same
ones as the web client. A token that does not say both is refused here, so Ace never acts as the user alone.
"""
import base64
import json
import time
from dataclasses import dataclass, replace
from typing import Any

import httpx

from gateway import message_of
from settings import Settings

TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN = "urn:ietf:params:oauth:token-type:access_token"
EXPIRY_MARGIN = 30           # seconds: a token is replaced before the gateway would refuse it
DEFAULT_LIFETIME = 300
CACHE_LIMIT = 256


def jwt_claims(token: str) -> dict[str, Any]:
    """The payload of a JWT, NOT verified: the gateway and AM verify. For the prompt and display, never for a decision."""
    try:
        body = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (IndexError, ValueError):
        return {}
    return claims if isinstance(claims, dict) else {}


class DelegationError(Exception):
    def __init__(self, detail: str, status: int | None = None) -> None:
        super().__init__(detail)
        self.status = status


@dataclass(frozen=True)
class Delegated:
    token: str
    claims: dict[str, Any]
    expires_at: float
    cached: bool = False


class Delegation:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self.agent_token: tuple[str, float] | None = None       # Ace's own token and when it expires
        self.cache: dict[str, Delegated] = {}                   # per user token, until the delegated one expires

    async def aclose(self) -> None:
        await self.http.aclose()

    async def delegated(self, user_token: str) -> Delegated:
        found = self.cache.get(user_token)
        if found and found.expires_at > time.monotonic():
            return replace(found, cached=True)
        reused = self.agent_token is not None and self.agent_token[1] > time.monotonic()
        try:
            answer = await self._exchange(user_token, await self._agent_token())
        except DelegationError as e:
            if not reused or e.status not in (400, 401):
                raise
            # AM may refuse the token Ace kept for itself (the domain was set up again, the keys changed): ask for a
            # new one, once. Otherwise Ace would refuse every user until the old token expires
            self.agent_token = None
            answer = await self._exchange(user_token, await self._agent_token())
        token = answer["access_token"]
        claims = jwt_claims(token)
        self._check(claims, jwt_claims(user_token))
        entry = Delegated(token, claims, time.monotonic() + lifetime(answer))
        self._remember(user_token, entry)
        return entry

    async def _exchange(self, user_token: str, actor_token: str) -> dict[str, Any]:
        return await self._post({
            "grant_type": TOKEN_EXCHANGE,
            "subject_token": user_token, "subject_token_type": ACCESS_TOKEN,
            "actor_token": actor_token, "actor_token_type": ACCESS_TOKEN,
            "requested_token_type": ACCESS_TOKEN,
        })

    def _check(self, delegated: dict[str, Any], user: dict[str, Any]) -> None:
        """A token the bank's policies cannot tell from the user's own would lift the agent's limits: it is not used."""
        act = delegated.get("act")
        if not isinstance(act, dict) or act.get("sub") != self.settings.agent_client_id:
            raise DelegationError("AM issued a token that does not name Ace as the actor")
        if not delegated.get("sub") or delegated["sub"] != user.get("sub"):
            raise DelegationError("AM issued a token for someone other than the user")

    async def _agent_token(self) -> str:
        if self.agent_token and self.agent_token[1] > time.monotonic():
            return self.agent_token[0]
        answer = await self._post({"grant_type": "client_credentials"})
        self.agent_token = (answer["access_token"], time.monotonic() + lifetime(answer))
        return self.agent_token[0]

    def _remember(self, user_token: str, entry: Delegated) -> None:
        now = time.monotonic()
        self.cache = {k: v for k, v in self.cache.items() if v.expires_at > now}
        if len(self.cache) >= CACHE_LIMIT:
            self.cache.pop(next(iter(self.cache)))
        self.cache[user_token] = entry

    async def _post(self, form: dict[str, str]) -> dict[str, Any]:
        """One call to AM's token endpoint, as the agent's application. Nothing of a token goes in an error."""
        try:
            response = await self.http.post(self.settings.am_token_url, data=form,
                                            auth=(self.settings.agent_client_id, self.settings.agent_client_secret))
        except httpx.HTTPError as e:
            raise DelegationError(f"AM did not answer ({type(e).__name__})") from e
        if response.status_code != 200:
            raise DelegationError(f"AM answered {response.status_code}: "
                                  f"{message_of(response.text, 'no message')}", response.status_code)
        try:
            answer = response.json()
        except ValueError:
            answer = None
        if not isinstance(answer, dict) or not isinstance(answer.get("access_token"), str):
            raise DelegationError("AM answered without a token", response.status_code)
        return answer


def lifetime(answer: dict[str, Any]) -> float:
    seconds = answer.get("expires_in")
    return max(0.0, (seconds if isinstance(seconds, (int, float)) else DEFAULT_LIFETIME) - EXPIRY_MARGIN)
