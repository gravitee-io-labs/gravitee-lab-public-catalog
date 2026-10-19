"""The Presenter view, for the person presenting: is everything ready, warm it up, put the data back, quiet the traffic."""
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urljoin

import httpx

import llm
import mcp_rpc
from am import AccessManagement
from chat import Chat
from management import Management
from sessions import NotSignedIn, Session, Sessions
from settings import Settings
from teams import TeamKeys
from upstream import Clients, UpstreamError, elapsed_ms, json_body

log = logging.getLogger("bank-web.presenter")

CACHE_PROBE = "What does an overdraft mean?"     # not the FAQ of the Developers view: that one still shows a miss first
ACE_AGENT = "Ace"
DASHBOARD = "ACME Bank - AI spend and safety"
WARM_MS = 5000                                   # a model that answers a tiny question slower than this was cold
CHECK_TIMEOUT = 40


# (id, group, what is checked, what to do when it is not right). Each runs the method `Presenter._<id>`. Nothing here is about a protection: whether
# one is on is Gamma's to say.
CHECKS = (
    ("am", "platform", "Access Management answers",
     "Re-seed the playground, then check that Access Management runs."),
    ("llm", "platform", "The LLM proxy answers",
     "Re-seed the playground. The gateway downloads its AI models at its first start: wait a few minutes."),
    ("mcp", "platform", "The MCP proxy answers",
     "Re-seed the playground: the MCP proxy or its plan is missing."),
    ("a2a", "platform", "The A2A proxy answers",
     "Re-seed the playground: the A2A proxy or its plan is missing."),
    ("workspace", "platform", "The AI workspace accepts a team key",
     "Re-seed the playground, then wait until the AI workspace shows DEPLOYED."),
    ("ollama", "platform", "Ollama answers and is warm",
     "Start Ollama, then press Warm up. Set OLLAMA_KEEP_ALIVE to keep the model loaded."),
    ("cache", "platform", "The semantic cache answers the second time",
     "Check that Redis runs and that its password is the core's, then re-seed."),
    ("identity", "platform", "Agent Identity lists Ace",
     "Re-seed the playground: it links Gamma to the ACME Bank domain of Access Management."),
    ("traffic", "data", "The traffic runs",
     "Press Resume traffic, or start bank-traffic from the Containers page."),
    ("dashboard", "data", "The dashboard has data",
     "Wait a few minutes for the traffic, or press Warm up."),
)


@dataclass
class Result:
    status: str                  # ok, warn or fail
    detail: str = ""


def _scalars(data: Any) -> dict:
    """What a service reports about itself, without the nested parts: the page lists it as it is."""
    return {k: v for k, v in data.items() if not isinstance(v, (dict, list))} if isinstance(data, dict) else {}


class Presenter:
    def __init__(self, clients: Clients, settings: Settings, am: AccessManagement, chat: Chat,
                 management: Management, keys: TeamKeys, sessions: Sessions):
        self.clients, self.settings, self.am, self.chat = clients, settings, am, chat
        self.management, self.keys, self.sessions = management, keys, sessions

    # -- the check -----------------------------------------------------------------------------------------------
    async def check(self) -> dict:
        """The checks of the platform. They need nobody: the two proxies that ask a user for a token (the MCP proxy, the A2A proxy) are called with none, and answer as their
        plan does, with a 401. The app holds no password and signs nobody in by itself."""
        started = time.monotonic()
        plan = [(key, group, label, fix, getattr(self, f"_{key}")) for key, group, label, fix in CHECKS]
        items = await asyncio.gather(*(self._run(spec) for spec in plan))
        return {"ready": all(item["status"] != "fail" for item in items), "items": items, "ms": elapsed_ms(started)}

    async def _run(self, spec: tuple) -> dict:
        key, group, label, fix, check = spec
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(check(), CHECK_TIMEOUT)
        except UpstreamError as e:
            result = Result("fail", e.message)
        except httpx.HTTPError as e:
            result = Result("fail", f"No answer: {type(e).__name__}")
        except asyncio.TimeoutError:
            result = Result("fail", f"No answer after {CHECK_TIMEOUT} s")
        except Exception as e:    # noqa: BLE001 - one broken check must not hide the others
            log.exception("check %s failed", key)
            result = Result("fail", f"Unexpected {type(e).__name__}")
        log.info("check %s %s %d ms", key, result.status, elapsed_ms(started))
        return {"id": key, "group": group, "label": label, "status": result.status, "detail": result.detail,
                "fix": "" if result.status == "ok" else fix, "ms": elapsed_ms(started)}

    async def _am(self) -> Result:
        found = await self.am.discovery()
        return Result("ok") if found.get("authorization_endpoint") and found.get("token_endpoint") else Result("fail", "Its discovery document has no login page")

    async def _llm(self) -> Result:
        response = await self.clients.gateway.get(f"{self.settings.llm_url.rstrip('/')}/models",
                                                  headers=llm.bearer(self.settings.dev_llm_api_key))
        return Result("ok") if response.status_code == 200 else Result("fail", f"HTTP {response.status_code}")

    @staticmethod
    def _asks_for_a_token(status: int) -> Result:
        """A proxy that is published with its plan refuses a call that carries no token: that 401 is the proof that it is there and that it is guarded. Another answer is
        a proxy that is not there (404) or one that lets anybody in."""
        return Result("ok", "It asks for a token") if status == 401 else Result("fail", f"HTTP {status}, not the 401 of its plan")

    async def _mcp(self) -> Result:
        return self._asks_for_a_token((await mcp_rpc.call(self.clients.gateway, self.settings.mcp_url, "tools/list", {})).status)

    async def _a2a(self) -> Result:
        response = await self.clients.gateway.get(f"{self.settings.ace_url.rstrip('/')}/.well-known/agent-card.json")
        return self._asks_for_a_token(response.status_code)

    async def _workspace(self) -> Result:
        key = await self.keys.key("team-care")
        workspace = self.keys.workspace
        if workspace.get("deploymentState") != "DEPLOYED":
            return Result("fail", f"State {workspace.get('deploymentState')}")
        url = f"{self.settings.gateway_url.rstrip('/')}{workspace.get('contextPath', '')}/models"
        response = await self.clients.gateway.get(url, headers={"Authorization": f"Bearer {key}"})
        return Result("ok") if response.status_code == 200 else Result("fail", f"HTTP {response.status_code}")

    async def _ask(self, content: str, **kwargs: Any) -> dict:
        return await llm.ask(self.clients.gateway, self.settings.llm_url, self.settings.dev_llm_api_key, content, **kwargs)

    @staticmethod
    def _unanswered(answer: dict) -> Result:
        """The Developers key may be out of tokens for the minute (a Send x10 just before): not a broken platform."""
        if answer["status"] == 429:
            return Result("warn", "The Developers key is at its limit: wait a minute")
        return Result("fail", f"HTTP {answer['status']}: {answer['message']}")

    async def _ollama(self) -> Result:
        # a digit in the question keeps the semantic cache from answering: the model must
        answer = await self._ask("Reply with the word ready. Check 1.", max_tokens=5)
        if answer["status"] != 200:
            return self._unanswered(answer)
        return Result("ok" if answer["ms"] < WARM_MS else "warn", f"{answer['ms']} ms")

    async def _cache(self) -> Result:
        await self._ask(CACHE_PROBE, max_tokens=60)
        second = await self._ask(CACHE_PROBE, max_tokens=60)
        if second["status"] != 200:
            return self._unanswered(second)
        if not second["cached"]:
            return Result("fail", "The second answer came from the model")
        return Result("ok", f"{second['ms']} ms")

    async def _identity(self) -> Result:
        """Agent Identity lists the agents of the AM domain Gamma is linked to: that domain is read first."""
        identity = f"{self.management.modules}/aim/identity"
        link = await self.management.get(f"{identity}/am-config")
        link = link if isinstance(link, dict) else {}
        environment, domain = link.get("environmentId"), link.get("defaultDomainId")
        if not (link.get("baseUrl") and link.get("hasAccessToken") and environment and domain):
            return Result("fail", "Gamma is not linked to Access Management")
        found = await self.management.get(
            f"{identity}/environments/{quote(environment, safe='')}/domains/{quote(domain, safe='')}/agents")
        names = [a.get("name") for a in found.get("items", [])] if isinstance(found, dict) else []
        if ACE_AGENT in names:
            return Result("ok", ACE_AGENT)
        return Result("fail", "Ace is not in the list of the linked domain")

    async def _traffic(self) -> Result:
        status = await self._traffic_status()
        return Result("warn", "Paused") if status["paused"] else Result("ok", "Running")

    async def _dashboard(self) -> Result:
        found = await self.management.get(f"{self.management.observability}/dashboards", page=1, perPage=100)
        if DASHBOARD not in [d.get("title") for d in found.get("data", [])]:
            return Result("fail", f"{DASHBOARD} does not exist")
        now = datetime.now(timezone.utc)
        answer = await self.management.post(f"{self.management.observability}/analytics/measures", {
            "timeRange": {"from": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "to": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
            "metrics": [{"name": "HTTP_REQUESTS", "measures": ["COUNT"]}]})
        requests = int(answer["metrics"][0]["measures"][0]["value"])
        if not requests:
            return Result("warn", "No request in the last hour")
        return Result("ok", f"{requests} requests in the last hour")

    # -- warm up ---------------------------------------------------------------------------------------------------
    async def warm_up(self, session: Session | None) -> dict:
        """The slow first calls, one after the other so the model is not asked twice at once. Ace is asked with the token of the person who is signed in."""
        steps: list[tuple[str, Callable[[], Awaitable[str]]]] = [
            ("Model smart", lambda: self._warm_model("acme-chat")),
            ("Model lite", lambda: self._warm_model("acme-lite")),
            ("Guard rails model", self._warm_guard),
            ("Ace", lambda: self._warm_ace(session)),
        ]
        results = []
        for label, step in steps:
            started = time.monotonic()
            try:
                detail, status = await step(), "ok"
            except (NotSignedIn, UpstreamError) as e:
                detail, status = e.message, "fail"
            results.append({"label": label, "status": status, "detail": detail, "ms": elapsed_ms(started)})
        log.info("warm up %s", [(r["label"], r["status"], r["ms"]) for r in results])
        return {"steps": results}

    async def _warm_model(self, model: str) -> str:
        answer = await self._ask("Reply with the word ready. Check 1.", max_tokens=5, model=model)
        if answer["status"] != 200:
            raise UpstreamError(f"HTTP {answer['status']}: {answer['message']}")
        return f"{answer['ms']} ms"

    async def _warm_guard(self) -> str:
        """The guard rails load their model at the first question they check, whatever it says: an ordinary one does, and no
        blocked prompt is counted in Gamma for a warm-up."""
        answer = await self._ask("Reply with the word ready. Check 2.", max_tokens=5)
        return f"HTTP {answer['status']}"

    async def _warm_ace(self, session: Session | None) -> str:
        """A first question to Ace, in a conversation of its own: the person's is not touched."""
        if session is None or session.persona is None:
            raise NotSignedIn("Choose who is asking first: Ace answers with their token")
        await self.am.valid_token(session)            # renewed if it is about to expire: the conversation below uses the token as it is
        person = session.persona
        probe = Session(time.time(), person, {person.id: session.signed[person.id]})
        turn = await self.chat.turn(probe, "Show my accounts and balances", True)
        return turn["answer"][:80]

    # -- reset and traffic -----------------------------------------------------------------------------------------
    async def reset(self) -> dict:
        """Balances and cards go back to the start, the traffic counters and every conversation start again."""
        bank = await self._post(self.clients.internal, urljoin(self.settings.mcp_direct_url, "/admin/reset"),
                                {"X-Admin-Token": self.settings.admin_token})
        traffic = await self._post(self.clients.internal, f"{self.settings.traffic_url.rstrip('/')}/reset")
        self.sessions.forget_conversations()
        log.info("reset bank=%s traffic=%s", bank["ok"], traffic["ok"])
        return {"bank": bank, "traffic": traffic}

    async def traffic(self, action: str | None) -> dict:
        if action:
            result = await self._post(self.clients.internal, f"{self.settings.traffic_url.rstrip('/')}/{action}")
            if not result["ok"]:
                raise UpstreamError(f"Traffic control answered {result['detail']}")
        return await self._traffic_status()

    async def _traffic_status(self) -> dict:
        try:
            response = await self.clients.internal.get(f"{self.settings.traffic_url.rstrip('/')}/status")
        except httpx.HTTPError as e:
            raise UpstreamError("Traffic control is not answering") from e
        body = json_body(response)
        if response.status_code != 200:
            raise UpstreamError(f"Traffic control answered HTTP {response.status_code}")
        return {"paused": bool(body.get("paused")) if isinstance(body, dict) else False, "status": _scalars(body)}

    @staticmethod
    async def _post(http: httpx.AsyncClient, url: str, headers: dict | None = None) -> dict:
        try:
            response = await http.post(url, headers=headers)
        except httpx.HTTPError as e:
            return {"ok": False, "detail": type(e).__name__}
        return {"ok": response.status_code < 300, "detail": f"HTTP {response.status_code}"}
