"""The APIs of the story, by the name the tracing pages know them by: the id Gamma's Tracing route needs.

The seed gives the LLM proxy and Ace's A2A proxy fixed ids; the MCP proxy and the AI workspace's own API take the
one Gravitee makes for them, which is read from the management API by name, once, and again after a failure or after the
platform says (404) that the API it named is gone.
"""
import logging
import time

from management import Management
from upstream import UpstreamError

log = logging.getLogger("bank-web.apis")

FIXED = {"llm": "00000000-0000-4000-8000-acb100000001", "a2a": "00000000-0000-4000-8000-acb200000001"}
NAMED = {"mcp": "ACME Bank MCP", "teams": "ACME Bank Teams"}
RETRY_AFTER = 30          # seconds before a name that was not found is looked for again


class Apis:
    def __init__(self, management: Management, clock=time.monotonic):
        self.management, self.clock = management, clock
        self._found: dict[str, str] = {}
        self._missed: dict[str, float] = {}

    def forget(self, key: str) -> None:
        """The platform made the API this id named again, with another id: look for it by its name next time."""
        self._found.pop(key, None)
        self._missed.pop(key, None)

    async def still(self, key: str, api_id: str) -> bool:
        """Whether the platform still has the API that `key` named with `api_id`. It has not where it answers 404: the API was made again with
        another id, which is forgotten here and read again by its name. Any other answer (or none) says nothing about it."""
        if key not in NAMED:
            return True
        try:
            await self.management.get(f"{self.management.v2}/apis/{api_id}")
        except UpstreamError as e:
            if e.upstream != 404:
                return True
            if self._found.get(key) == api_id:
                self.forget(key)
            return False
        return True

    async def id(self, key: str) -> str | None:
        """The id of the API behind `key` (llm, a2a, mcp, teams), or None when the platform does not say."""
        if key in FIXED:
            return FIXED[key]
        if key in self._found:
            return self._found[key]
        if key not in NAMED or self.clock() - self._missed.get(key, -RETRY_AFTER) < RETRY_AFTER:
            return None
        try:
            found = await self.management.get(f"{self.management.v2}/apis", q=NAMED[key], perPage=20)
        except UpstreamError as e:
            log.info("the id of %s is not known yet: %s", NAMED[key], e.message)
            self._missed[key] = self.clock()
            return None
        match = next((a for a in found.get("data", []) if a.get("name") == NAMED[key]), None) if isinstance(found, dict) else None
        if match is None or not match.get("id"):
            self._missed[key] = self.clock()
            return None
        self._found[key] = match["id"]
        return match["id"]
