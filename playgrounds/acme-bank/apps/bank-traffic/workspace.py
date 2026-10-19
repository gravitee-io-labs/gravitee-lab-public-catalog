"""The AI workspace of the teams: where it is served and the API keys of its users, read from the Gamma API.

Gravitee generates the keys when the seed adds a user, so nothing here knows them in advance: they are read at
start, and again after any 401 (the user is removed and added again, or the workspace is seeded again).
"""
import httpx

from cast import TEAMS
from settings import Settings
from wire import USER_AGENT, PlatformError, message_of

PAGE = 100


class Workspace:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        auth = None if settings.apim_token else httpx.BasicAuth(*settings.apim_login)
        headers = {"User-Agent": USER_AGENT}
        if settings.apim_token:
            headers["Authorization"] = f"Bearer {settings.apim_token}"
        self._http = httpx.AsyncClient(headers=headers, auth=auth, timeout=30, transport=transport)
        scope = f"organizations/{settings.org}/environments/{settings.env}"
        self._aim = f"{settings.gamma_url}/gamma/{scope}/modules/aim"
        self._users = f"{settings.apim_url}/management/organizations/{settings.org}/users"
        self.entrypoint = ""
        self._keys: dict[str, str] = {}

    @property
    def loaded(self) -> bool:
        return bool(self._keys)

    def key(self, team: str) -> str:
        return self._keys[team]

    async def load(self, deployed: bool = False) -> None:
        """Finds the workspace by its name and reads the key of each team. `deployed` also asks for what the gateway
        serves to be what the console shows: a first start waits for it, a new key after a 401 does not."""
        workspace = await self._find(self._settings.workspace_name, deployed)
        keys = {team: await self._key_of(workspace["id"], team) for team in TEAMS}
        self.entrypoint = self._settings.gateway_url + workspace["contextPath"]
        self._keys = keys

    async def _find(self, name: str, deployed: bool) -> dict:
        found = await self._get(f"{self._aim}/ai-workspaces", {"q": name, "page": 0, "perPage": PAGE})
        match = next((w for w in found.get("content", []) if w.get("name") == name), None)
        if match is None:
            raise PlatformError(f"the AI workspace {name} does not exist yet")
        if deployed and match.get("deploymentState") != "DEPLOYED":
            raise PlatformError(f"the AI workspace {name} is {match.get('deploymentState')}, not DEPLOYED")
        detail = await self._get(f"{self._aim}/ai-workspaces/{match['id']}")
        if not detail.get("contextPath"):
            raise PlatformError(f"the AI workspace {name} has no model yet, so it serves nothing")
        return detail

    async def _key_of(self, workspace_id: str, team: str) -> str:
        user = await self._platform_user(team)
        member = next((m for m in await self._members(workspace_id) if m.get("userId") == user), None)
        if member is None:
            raise PlatformError(f"{team} is not a user of the AI workspace")
        answer = await self._get(f"{self._aim}/ai-workspaces/{workspace_id}/users/{member['subscriptionId']}/api-key")
        return answer["apiKey"]

    async def _platform_user(self, source_id: str) -> str:
        found = await self._get(self._users, {"q": source_id, "size": PAGE})
        user = next((u for u in found.get("data", [])
                     if u.get("source") == "gravitee" and u.get("sourceId") == source_id), None)
        if user is None:
            raise PlatformError(f"the platform has no user {source_id} yet")
        return user["id"]

    async def _members(self, workspace_id: str) -> list[dict]:
        members, page = [], 1
        while True:
            body = await self._get(f"{self._aim}/ai-workspaces/{workspace_id}/users", {"page": page, "perPage": PAGE})
            members += body.get("data", [])
            if not body.get("data") or len(members) >= body.get("pagination", {}).get("totalCount", 0):
                return members
            page += 1

    async def _get(self, url: str, params: dict | None = None) -> dict:
        try:
            answer = await self._http.get(url, params=params)
        except httpx.HTTPError as e:
            raise PlatformError(f"the management API does not answer ({type(e).__name__})") from e
        if answer.status_code != 200:
            raise PlatformError(f"the management API answered HTTP {answer.status_code}: {message_of(answer.text)}",
                                answer.status_code)
        try:
            return answer.json()
        except ValueError as e:
            raise PlatformError("the management API answered something that is not JSON") from e

    async def aclose(self) -> None:
        await self._http.aclose()
