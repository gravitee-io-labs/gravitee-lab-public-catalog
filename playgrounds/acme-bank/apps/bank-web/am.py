"""Access Management, for the web app: the address of its login page, the exchange of the code that comes back from it, and the refresh.

The page signs a person in with the authorization code flow and PKCE, as a real application does: Access Management shows its own login page, the browser
comes back with a code, and this server (the client, which keeps its secret) exchanges the code and the PKCE verifier for the tokens, on the back channel. There is
no password grant and no password: when a refresh is not accepted, the person signs in again, on the same page.
"""
import time
from urllib.parse import urlencode

import httpx

from people import Persona
from sessions import NotSignedIn, Session, Tokens
from settings import Settings
from upstream import UpstreamError

SCOPE = "openid profile email"
EXPIRY_MARGIN = 30       # seconds: a token about to expire is renewed before the gateway refuses it


class AccessManagement:
    def __init__(self, http: httpx.AsyncClient, settings: Settings):
        self.http, self.settings = http, settings

    def authorize_url(self, *, state: str, challenge: str, redirect_uri: str, persona: Persona) -> str:
        """Where the browser goes to sign a person in. `login_hint` fills in the user name; `prompt=login` shows the form even when Access Management knows
        somebody else already, so that the person who is chosen is the one who signs in."""
        query = urlencode({
            "response_type": "code", "client_id": self.settings.web_client_id, "redirect_uri": redirect_uri, "scope": SCOPE, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256", "login_hint": persona.username, "prompt": "login"})
        return f"{self.settings.am_authorize_url}?{query}"

    async def exchange(self, code: str, verifier: str, redirect_uri: str) -> Tokens:
        """The tokens for a code, with the verifier of the sign-in that asked for it and the secret of the client."""
        return await self._token(grant_type="authorization_code", code=code, code_verifier=verifier, redirect_uri=redirect_uri)

    async def valid_token(self, session: Session) -> str:
        """The access token of the person who asks, renewed when it is about to expire. Two calls that find it expiring renew it once: the second takes what the
        first got (a refresh token is used once where Access Management rotates them)."""
        persona = session.persona
        if persona is None or session.tokens is None:
            raise NotSignedIn("Sign in first")
        if session.tokens.expires_at - time.time() < EXPIRY_MARGIN:
            async with session.renewing:
                tokens = session.signed.get(persona.id)
                if tokens is None:                      # the sign-in ended while this call waited
                    raise NotSignedIn(f"Your sign-in as {persona.first} has ended. Sign in again.", persona)
                if tokens.expires_at - time.time() < EXPIRY_MARGIN:
                    session.signed[persona.id] = await self._renew(session, persona, tokens)
        return session.signed[persona.id].access_token

    async def _renew(self, session: Session, persona: Persona, current: Tokens) -> Tokens:
        """A refresh token Access Management does not accept (it restarted, the session is older than the token) ends the sign-in: the person signs in again, at
        the login page. Nothing signs them in behind their back."""
        if current.refresh_token:
            try:
                renewed = await self._token(grant_type="refresh_token", refresh_token=current.refresh_token)
                renewed.refresh_token = renewed.refresh_token or current.refresh_token
                return renewed
            except UpstreamError as e:
                if e.upstream not in (400, 401):          # it did not answer, or failed: that is not a refusal of the refresh token, and not the end of the sign-in
                    raise
        session.forget(persona)
        raise NotSignedIn(f"Your sign-in as {persona.first} has ended. Sign in again.", persona)

    async def discovery(self) -> dict:
        """What Access Management says of itself (OpenID Connect discovery), read from the address of its token endpoint: it answers, and it is the domain's."""
        url = self.settings.am_token_url.rsplit("/oauth/token", 1)[0] + "/oidc/.well-known/openid-configuration"
        try:
            response = await self.http.get(url)
        except httpx.HTTPError as e:
            raise UpstreamError("Access Management is not answering") from e
        if response.status_code != 200:
            raise UpstreamError(f"Access Management answered HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as e:
            raise UpstreamError("Access Management answered without its discovery document") from e
        return body if isinstance(body, dict) else {}

    async def _token(self, **form: str) -> Tokens:
        try:
            response = await self.http.post(self.settings.am_token_url, data=form,
                                            auth=(self.settings.web_client_id, self.settings.web_client_secret))
        except httpx.HTTPError as e:
            raise UpstreamError("Access Management is not answering") from e
        if response.status_code != 200:
            raise UpstreamError(f"Access Management refused the sign-in (HTTP {response.status_code})", upstream=response.status_code)
        try:
            body = response.json()
            return Tokens(body["access_token"], body.get("refresh_token"), time.time() + int(body.get("expires_in", 300)))
        except (ValueError, KeyError, TypeError) as e:
            raise UpstreamError("Access Management answered without an access token") from e
