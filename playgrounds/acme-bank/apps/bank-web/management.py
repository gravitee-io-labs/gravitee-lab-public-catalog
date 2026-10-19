"""Reads from the APIM management API, which also serves Gamma, with the credentials the seed uses."""
from typing import Any

import httpx

from settings import Settings
from upstream import UpstreamError, json_body, message_of


class Management:
    def __init__(self, http: httpx.AsyncClient, settings: Settings):
        self.http = http
        base = settings.apim_management_url.rstrip("/")
        self.v1 = f"{base}/management/organizations/{settings.apim_org}"
        self.v2 = f"{base}/management/v2/organizations/{settings.apim_org}/environments/{settings.apim_env}"
        self.modules = f"{base}/gamma/organizations/{settings.apim_org}/environments/{settings.apim_env}/modules"
        self.observability = f"{base}/gamma/organizations/{settings.apim_org}/environments/{settings.apim_env}/observability"
        self._headers = {"Authorization": f"Bearer {settings.apim_token}"} if settings.apim_token else {}
        self._auth = None if settings.apim_token else (settings.apim_username, settings.apim_password)

    async def get(self, url: str, **params: Any) -> Any:
        return await self._send("GET", url, params=params)

    async def post(self, url: str, body: dict, **params: Any) -> Any:
        return await self._send("POST", url, json=body, params=params)

    async def _send(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = await self.http.request(method, url, headers=self._headers, auth=self._auth, **kwargs)
        except httpx.HTTPError as e:
            raise UpstreamError("The management API is not answering") from e
        body = json_body(response)
        if response.status_code in (401, 403):
            raise UpstreamError(f"The management API refused the credentials (HTTP {response.status_code})", 503)
        if response.status_code >= 400:
            # what the platform said (its own words, a stack text, an internal host) is for the log, not for the page
            raise UpstreamError(f"The management API answered HTTP {response.status_code}", 502, upstream=response.status_code,
                                detail=message_of(body)[:200])
        return body
