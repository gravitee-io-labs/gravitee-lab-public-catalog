"""The services bank-web calls, as in-memory fakes: Access Management, the gateway (A2A, LLM, MCP and workspace
proxies), the bank's MCP server, the APIM management API and the traffic generator.

One transport routes every request by host to the fake that plays it, so the app under test runs its real code
over no socket. `python -m tests.fake_stack` serves the app over these fakes, for the page and tests/smoke.py.
"""

import asyncio
import base64
import hashlib
import itertools
import json
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode

import httpx
from a2a.helpers import new_data_part, new_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from settings import Settings
from upstream import Clients

CLIENT = ("acme-bank-web", "web-secret")
DEMO_PASSWORD = "demo-password"
DEV_KEY = "dev-key"
ADMIN = ("admin", "admin-password")
ADMIN_TOKEN = "bank-admin-token"
TOKEN = "management-token"
USERS = {
    "alice@acme-bank.test": {
        "name": "Alice Martin",
        "role": "customer",
        "customer_id": "C-1001",
        "accounts": ["ACC-1001", "ACC-1002"],
    },
    "bob@acme-bank.test": {"name": "Bob Chen", "role": "customer", "customer_id": "C-2001", "accounts": ["ACC-2001"]},
    "tina@acme-bank.test": {"name": "Tina Torres", "role": "teller"},
}
TOOLS = [
    "list_accounts",
    "get_balance",
    "list_transactions",
    "transfer_funds",
    "freeze_card",
    "get_exchange_rate",
    "simulate_loan",
    "find_branches",
]
TEAM_USERS = {"team-hackathon": "u-1", "team-care": "u-2", "team-fraud": "u-3"}
LLM_API, MCP_API, TEAMS_API = "00000000-0000-4000-8000-acb100000001", "44ab2daf-d0e3-362c-8d88-2d741faf7eab", "4b8dd261-28b5-4bb1-8dd2-6128b5cbb1f7"


def gateway_ids(kind: str, n: int) -> dict[str, str]:
    """The two ids the gateway gives an answer: its transaction's and its request's (the same only where the caller sent no transaction id)."""
    return {"x-gravitee-transaction-id": f"tx-{kind}-{n}", "x-gravitee-request-id": f"req-{kind}-{n}"}


class Controls:
    """What the fake gateway enforces, each on until a test switches it off (the lab starts them off): the guard rails, the filter of the tools by role, the
    policy engine, the cap on what an agent moves, the router of the teams."""

    def __init__(self) -> None:
        self.guard = self.tools = self.pep = self.cap = self.router = True


def fake_jwt(claims: dict) -> str:
    def encode(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{encode({'alg': 'none', 'typ': 'JWT'})}.{encode(claims)}.signature"


def bearer_claims(header: str | None) -> dict | None:
    """The claims of the token in an Authorization header, None when there is no bearer token."""
    if not header or not header.startswith("Bearer "):
        return None
    body = header[7:].split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def claims_of(request: Request) -> dict | None:
    return bearer_claims(request.headers.get("authorization"))


def basic(request: Request) -> tuple[str, str] | None:
    header = request.headers.get("authorization", "")
    if not header.startswith("Basic "):
        return None
    user, _, password = base64.b64decode(header[6:]).decode().partition(":")
    return user, password


class FakeAm:
    """Access Management's authorization code flow, for the app's sign-in: the login page is `authorize` (what the browser does on it is the test's, as
    `Browser.sign_in` plays it: the person types the password and the browser is sent back with a code), the token endpoint exchanges a code (and the PKCE verifier
    that goes with the challenge the login page was given) or a refresh token. There is no password grant: the app has none."""

    def __init__(self) -> None:
        self.log: list[dict] = []
        self.logins: list[dict] = []               # what the login page was asked: its query
        self.expires_in = 300
        self.down = False
        self.delay = 0.0                           # how long the token endpoint takes to answer: with some, two calls that overlap really do
        self.refuses_login = False                 # the person does not sign in: Access Management sends the browser back with an error
        self.signs_in_as: str | None = None        # who types their password, if that is not who the app asked for (the `login_hint`)
        self.discovery_document: dict | None = None   # what the discovery document says instead of what it says
        self._codes: dict[str, dict] = {}
        self._refresh: dict[str, str] = {}
        self._count = itertools.count(1)
        self._codes_made = itertools.count(1)

    def app(self) -> Starlette:
        return Starlette(routes=[Route("/acme-bank/oauth/token", self.token, methods=["POST"]),
                                 Route("/acme-bank/oauth/authorize", self.authorize, methods=["GET"]),
                                 Route("/acme-bank/oidc/.well-known/openid-configuration", self.discovery, methods=["GET"])])

    async def discovery(self, request: Request) -> Response:
        if self.down:
            return Response(status_code=503)
        base = "http://am.test/acme-bank"
        if self.discovery_document is not None:
            return JSONResponse(self.discovery_document)
        return JSONResponse({"issuer": f"{base}/oidc", "authorization_endpoint": f"{base}/oauth/authorize", "token_endpoint": f"{base}/oauth/token"})

    async def authorize(self, request: Request) -> Response:
        """The login page and the person who signs in on it, in one step: the browser is sent back to the redirect URI with a code (or an error), and the state."""
        query = dict(request.query_params)
        self.logins.append(query)
        redirect, state = query.get("redirect_uri", ""), query.get("state", "")
        if (query.get("response_type") != "code" or query.get("client_id") != CLIENT[0] or query.get("code_challenge_method") != "S256"
                or not query.get("code_challenge") or not redirect):
            return JSONResponse({"error": "invalid_request"}, status_code=400)           # the login page's own error: the browser is not sent back
        if self.refuses_login:
            return Response(status_code=302, headers={"location": f"{redirect}?{urlencode({'error': 'access_denied', 'state': state})}"})
        user = self.signs_in_as or query.get("login_hint", "")
        code = f"code-{next(self._codes_made)}"
        self._codes[code] = {"user": user, "challenge": query["code_challenge"], "redirect_uri": redirect}
        return Response(status_code=302, headers={"location": f"{redirect}?{urlencode({'code': code, 'state': state})}"})

    async def token(self, request: Request) -> Response:
        form = dict(parse_qsl((await request.body()).decode()))
        self.log.append({"form": form, "authorization": basic(request)})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.down:
            return Response(status_code=503)
        if basic(request) != CLIENT:
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        if form.get("grant_type") == "authorization_code":
            granted = self._codes.pop(form.get("code", ""), None)          # a code is used once
            verifier = form.get("code_verifier", "")
            sent = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if granted is None or form.get("redirect_uri") != granted["redirect_uri"] or sent != granted["challenge"]:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            user = granted["user"]
        elif form.get("grant_type") == "refresh_token" and form.get("refresh_token") in self._refresh:
            user = self._refresh[form["refresh_token"]]
        else:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        n = next(self._count)
        self._refresh[f"refresh-{n}"] = user
        claims = {"sub": f"id-{user}", "username": user, "n": n, **USERS.get(user, {"name": "Somebody Else", "role": "customer"})}
        return JSONResponse(
            {
                "access_token": fake_jwt(claims),
                "refresh_token": f"refresh-{n}",
                "expires_in": self.expires_in,
                "token_type": "Bearer",
            }
        )


class FakeAce(AgentExecutor):
    """An Ace that answers with the trace it is told to (`reply`), or one that fits the question: a balance, a customer asking for another's
    accounts, an agent asked to move more than EUR 500, an injection. Its trace is the real Ace's: the token exchange, the list of tools, a call to the
    model that chooses, the tools, a call to the model that writes the answer (`story`); its data part says the tools it was offered."""

    def __init__(self, protected: bool = True, controls: "Controls | None" = None) -> None:
        self.protected = protected
        self.controls = controls or Controls()
        self.log: list[dict] = []
        self.reply: tuple[str, list, dict | None] | None = None
        self.fails_with: Exception | None = None
        self._ids = itertools.count(1)

    async def execute(self, context, event_queue):
        if self.fails_with:
            raise self.fails_with
        headers = context.call_context.state["headers"]
        text = context.get_user_input()
        self.log.append(
            {
                "text": text,
                "authorization": headers.get("authorization"),
                "context_id": context.context_id,
                "a2a_version": headers.get("a2a-version"),
            }
        )
        offered = None
        if self.reply:
            answer, trace, claims = self.reply
        else:
            answer, trace, claims, offered = self.scripted(text, bearer_claims(headers.get("authorization")) or {})
        data = {"trace": trace, **({"tools": offered} if offered is not None else {}), **({"delegated_claims": claims} if claims else {})}
        await event_queue.enqueue_event(
            new_message([new_text_part(answer), new_data_part(data)], context_id=context.context_id)
        )

    async def cancel(self, context, event_queue):
        raise NotImplementedError

    def hop(self, step: str, **fields: Any) -> dict:
        n = next(self._ids)
        ids = {"transaction_id": f"tx-{step}-{n}", "request_id": f"req-{step}-{n}"} if self.protected and step != "exchange" else {}      # the exchange is AM's, not the gateway's
        return {"step": step, "outcome": "ok", "status": 200, **ids, **fields}

    def story(self, offered: list[str], *tools: dict, first: dict | None = None, answers: bool = True) -> list:
        """What the real Ace reports: its token (when it acts for the user), the tools it lists, the call to the model that chooses them (`first`: that call
        as it went, a refusal for instance), the tool calls, and the call that writes the answer."""
        model = {"name": "acme-chat", "ms": 410}
        rows = [self.hop("exchange", name="token-exchange", ms=14, detail="issued: sub = the user, act.sub = ace-agent")] if self.protected else []
        rows.append(self.hop("tool", name="tools/list", ms=9, detail=f"{len(offered)} tools"))
        rows.append(self.hop("llm", **(first or {**model, "detail": f"1161 tokens, {len(tools)} tool call(s)"})))
        if first is None:
            rows += tools
            if answers:
                rows.append(self.hop("llm", **{**model, "ms": 655, "detail": "1354 tokens, 0 tool call(s)"}))
        return rows

    def scripted(self, text: str, claims: dict) -> tuple[str, list, dict | None, list[str]]:
        lower = text.lower()
        customer = self.protected and self.controls.tools and claims.get("role") == "customer"
        offered = [t for t in TOOLS if t != "freeze_card"] if customer else list(TOOLS)
        delegated = (
            {"sub": claims.get("sub"), "role": claims.get("role"), "act": {"sub": "ace-agent"}}
            if self.protected
            else None
        )
        if "ignore all previous" in lower and self.controls.guard:
            blocked = self.story(offered, first={"name": "acme-chat", "outcome": "blocked", "status": 400, "ms": 95, "blocked_by": "llm-proxy",
                                                 "detail": "AI prompt validation detected. Reason: [MALICIOUS]"})
            return "I can't help with that: the request was blocked by ACME's AI policy.", blocked, delegated, offered
        if (
            self.protected
            and self.controls.pep
            and "c-1001" in lower
            and claims.get("role") == "customer"
            and claims.get("customer_id") != "C-1001"
        ):
            read = self.hop("tool", name="list_accounts", arguments={"customer_id": "C-1001"}, outcome="denied", status=403, ms=9,
                            detail="Not allowed by ACME authorization policy")
            return "I cannot show the accounts of another customer.", self.story(offered, read), delegated, offered
        if self.protected and self.controls.pep and self.controls.cap and "600" in lower:
            move = self.hop("tool", name="transfer_funds", arguments={"from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 600},
                            outcome="denied", status=403, ms=11, detail="Not allowed by ACME authorization policy")
            return "The bank does not let me move more than EUR 500.", self.story(offered, move), delegated, offered
        if "freeze" in lower:
            if customer:
                return "I cannot freeze cards.", self.story(offered, answers=False), delegated, offered
            denied = self.protected and self.controls.pep and claims.get("role") == "customer"
            freeze = self.hop("tool", name="freeze_card", arguments={"card_id": "CARD-1001"}, ms=8)
            if denied:
                freeze.update(outcome="denied", status=403, detail="Not allowed by ACME authorization policy")
            return "Done." if not denied else "I may not freeze that card.", self.story(offered, freeze), delegated, offered
        if "600" in lower:  # the cap, or the whole policy engine, is off: nothing stops the agent
            move = self.hop("tool", name="transfer_funds", ms=11, arguments={"from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 600})
            return "Done: EUR 600 moved.", self.story(offered, move), delegated, offered
        if "c-1001" in lower and (not self.protected or not self.controls.pep):  # anyone reads anyone's accounts
            read = self.hop("tool", name="list_accounts", arguments={"customer_id": "C-1001"}, ms=7)
            return "Customer C-1001 has ACC-1001 (EUR 4,820.55) and ACC-1002 (EUR 15,300.00).", self.story(offered, read), None, offered
        balance = self.hop(
            "tool",
            name="get_balance",
            arguments={"account_id": "ACC-1001", "access_token": "must-not-show"},
            detail='{"account_id": "ACC-1001", "balance": 4820.55, "currency": "EUR"}',   # what the bank's tool says, as the agent keeps it
            ms=12,
        )
        return "Your balance is EUR 4,820.55.", self.story(offered, balance), delegated, offered


def ace_app(ace: FakeAce, url: str) -> Starlette:
    card = AgentCard(
        name="Ace",
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=False),
    )
    handler = DefaultRequestHandler(agent_executor=ace, task_store=InMemoryTaskStore(), agent_card=card)
    return Starlette(routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, rpc_url="/")])


class Behind:
    """The gateway in front of an app: no bearer token, no answer; every answer carries a transaction id."""

    def __init__(self, app, prefix: str, ids: itertools.count, require_bearer: bool = True) -> None:
        self.app, self.prefix, self.ids, self.require_bearer = app, prefix, ids, require_bearer
        self.refuse_with: int | None = None
        self.answer_with: Response | None = None  # served as it is instead of the app's answer
        self.request_ids = True                   # the gateway gives each answer the id of its request (it always does: a test can take it away)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if self.answer_with:
            return await self.answer_with(scope, receive, send)
        headers = dict(scope["headers"])
        if self.refuse_with or (self.require_bearer and not headers.get(b"authorization", b"").startswith(b"Bearer ")):
            status, n = self.refuse_with or 401, next(self.ids)
            ids = {"x-gravitee-transaction-id": f"{self.prefix}-{n}", **({"x-gravitee-request-id": f"req-{self.prefix.removeprefix('tx-')}-{n}"} if self.request_ids else {})}
            await JSONResponse({"message": "Unauthorized", "http_status_code": status}, status_code=status, headers=ids)(scope, receive, send)      # a refusal has its ids too
            return

        async def tagged(message):
            if message["type"] == "http.response.start":
                n = next(self.ids)
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-gravitee-transaction-id", f"{self.prefix}-{n}".encode()),
                    *([(b"x-gravitee-request-id", f"req-{self.prefix.removeprefix('tx-')}-{n}".encode())] if self.request_ids else []),
                ]
            await send(message)

        await self.app(scope, receive, tagged)


class FakeLlm:
    """The LLM proxy: the Developers key, a token limit per minute, a guard rail and a semantic cache."""

    def __init__(self, ids: itertools.count, controls: Controls | None = None) -> None:
        self.ids, self.limit, self.used, self.cached, self.log = ids, 3000, 0, set(), []
        self.controls = controls or Controls()

    def routes(self) -> list[Route]:
        return [
            Route("/acme-bank/llm/chat/completions", self.chat, methods=["POST"]),
            Route("/acme-bank/llm/models", self.models, methods=["GET"]),
        ]

    def _key(self, request: Request) -> str | None:
        header = request.headers.get("authorization", "")
        return header[7:] if header.startswith("Bearer ") else None

    async def models(self, request: Request) -> Response:
        if self._key(request) != DEV_KEY:
            return JSONResponse({"message": "Unauthorized", "http_status_code": 401}, status_code=401)
        return JSONResponse({"data": [{"id": "acme-chat"}]})

    async def chat(self, request: Request) -> Response:
        body = await request.json()
        self.log.append({"authorization": request.headers.get("authorization"), "body": body})
        tx = gateway_ids("llm", next(self.ids))
        if self._key(request) != DEV_KEY:
            return JSONResponse({"message": "Unauthorized", "http_status_code": 401}, status_code=401, headers=tx)
        text = body["messages"][-1]["content"]
        if "ignore all previous instructions" in text.lower() and self.controls.guard:
            return JSONResponse(
                {"message": "AI prompt validation detected. Reason: [MALICIOUS]", "http_status_code": 400},
                status_code=400,
                headers=tx,
            )
        if self.used >= self.limit:
            return JSONResponse(
                {
                    "message": "Rate limit exceeded! You reached the limit of 3000 tokens per 1 minutes",
                    "http_status_code": 429,
                },
                status_code=429,
                headers={**tx, **self._rate()},
            )
        if not any(c.isdigit() for c in text) and text in self.cached:
            return JSONResponse(
                {
                    "id": "resp_llmproxy",
                    "model": body["model"],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    "choices": [{"message": {"content": "A cached answer."}}],
                },
                headers=tx,
            )
        self.cached.add(text)
        prompt, completion = self._usage(text, body)
        self.used += prompt + completion
        return JSONResponse(
            {
                "id": "chatcmpl-1",
                "model": "qwen3:1.7b",
                "usage": {
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": prompt + completion,
                },
                "choices": [{"message": {"content": "A model answer."}}],
            },
            headers={**tx, **self._rate()},
        )

    @staticmethod
    def _usage(text: str, body: dict) -> tuple[int, int]:
        """A question that asks for detail uses the whole max_tokens; any other question gets a short answer."""
        return (30, body["max_tokens"]) if "in detail" in text else (100, 20)

    def _rate(self) -> dict[str, str]:
        return {
            "x-token-rate-limit-limit": str(self.limit),
            "x-token-rate-limit-remaining": str(max(0, self.limit - self.used)),
            "x-token-rate-limit-reset": "1791000000000",
        }


class FakeMcp:
    """An MCP proxy with an OAuth2 plan and an authorization policy, or the bank's server with nothing in front."""

    def __init__(self, ids: itertools.count, protected: bool = True, controls: Controls | None = None) -> None:
        self.ids, self.protected, self.log = ids, protected, []
        self.controls = controls or Controls()
        self.fail_list = False                       # tools/list answers 503 (the tool list of a person cannot be read)

    async def rpc(self, request: Request) -> Response:
        body = await request.json()
        claims = claims_of(request)
        self.log.append(
            {
                "method": body["method"],
                "params": body.get("params"),
                "authorization": request.headers.get("authorization"),
            }
        )
        tx = gateway_ids("mcp", next(self.ids)) if self.protected else {}
        if self.protected and claims is None:
            return JSONResponse({"message": "Unauthorized", "http_status_code": 401}, status_code=401, headers=tx)
        if body["method"] == "tools/list" and self.fail_list:
            return JSONResponse({"message": "Service unavailable"}, status_code=503, headers=tx)
        if body["method"] == "tools/list":
            names = (
                TOOLS
                if not self.protected or claims.get("role") == "teller" or not self.controls.tools
                else [t for t in TOOLS if t != "freeze_card"]
            )
            return JSONResponse(
                {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": n} for n in names]}}, headers=tx
            )
        tool, arguments = body["params"]["name"], body["params"]["arguments"]
        if self.protected and self.controls.pep and (reason := self._forbidden(claims, tool, arguments)):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32001,
                        "message": reason,
                        "data": {
                            "action": "acme-bank-mcp.transfer_funds",
                            "subject": claims["username"].split("@")[0],
                            "requestId": tx.get("x-gravitee-request-id"),
                        },
                    },
                },
                status_code=403,
                headers=tx,
            )
        if tool != "transfer_funds":
            return JSONResponse(
                {"jsonrpc": "2.0", "id": 1, "result": {"isError": False, "content": [{"type": "text", "text": "{}"}],
                                                       "structuredContent": {"customer_id": arguments.get("customer_id")}}},
                headers=tx,
            )
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "isError": False,
                    "content": [{"type": "text", "text": "done"}],
                    "structuredContent": {"id": "TR-1", "status": "done", "amount": arguments["amount"]},
                },
            },
            headers=tx,
        )

    @staticmethod
    def _forbidden(claims: dict, tool: str, arguments: dict) -> str | None:
        denied = "Not allowed by ACME authorization policy"
        if tool == "list_accounts":      # a customer reads their own accounts, a teller anyone's
            if claims.get("role") == "teller":
                return None
            return None if arguments.get("customer_id") == claims.get("customer_id") else denied
        if tool != "transfer_funds":
            return None
        amount = arguments["amount"]
        if claims.get("role") != "customer" or arguments["from_account"] not in claims.get("accounts", []):
            return denied
        if amount > 10000:
            return denied
        return denied if amount < 1 else None

    def app(self) -> Starlette:
        return Starlette(routes=[Route("/acme-bank/mcp", self.rpc, methods=["POST"])])


class FakeBank:
    """The bank's MCP server on its own port: no protection, and the reset the Presenter view calls."""

    def __init__(self) -> None:
        self.mcp, self.resets = FakeMcp(itertools.count(), protected=False), 0

    async def reset(self, request: Request) -> Response:
        if request.headers.get("x-admin-token") != ADMIN_TOKEN:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        self.resets += 1
        return JSONResponse({"status": "reset"})

    def app(self) -> Starlette:
        return Starlette(
            routes=[Route("/", self.mcp.rpc, methods=["POST"]), Route("/admin/reset", self.reset, methods=["POST"])]
        )


class FakeWorkspace:
    """The AI workspace: one API key per team and a cost budget per team, in millionths of a dollar, as the gateway keeps it.

    Before it lets a call in, the gateway adds what it expects the call to cost (the cost of a long answer, or 10,000 for a team's
    first call) to what the team has spent. It answers 429 when that is past the budget; the router moves the team to the lite
    model from half of the budget on, deciding on that same figure; and the headers carry it, the call's own cost not yet in it.
    So the headers of an answer say how much was held when it was let in, which is what the router saw.
    """

    LONG, SHORT, LITE = 21_650, 2_850, 8_660   # what a long answer on smart, a short one and a long one on lite cost
    FIRST = 10_000                             # what it expects of a team's first call

    def __init__(self, ids: itertools.count, controls: Controls | None = None) -> None:
        self.ids, self.log = ids, []
        self.controls = controls or Controls()
        self.keys = {team: f"key-{team}-1" for team in TEAM_USERS}
        self.budget = {"team-hackathon": 120_000, "team-care": 5_000_000, "team-fraud": 2_000_000}
        self.spent = dict.fromkeys(TEAM_USERS, 0)
        self.asked = dict.fromkeys(TEAM_USERS, 0)

    def routes(self) -> list[Route]:
        return [
            Route("/acme-bank-teams/chat/completions", self.chat, methods=["POST"]),
            Route("/acme-bank-teams/models", self.models, methods=["GET"]),
        ]

    @staticmethod
    def _key(request: Request) -> str:
        return request.headers.get("authorization", "").removeprefix("Bearer ")   # as the gateway reads it

    def _team(self, request: Request) -> str | None:
        key = self._key(request)
        return next((team for team, k in self.keys.items() if k == key), None)

    async def models(self, request: Request) -> Response:
        if self._team(request) is None:
            return JSONResponse({"message": "Unauthorized", "http_status_code": 401}, status_code=401)
        return JSONResponse({"data": []})

    async def chat(self, request: Request) -> Response:
        body = await request.json()
        team = self._team(request)
        self.log.append({"key": self._key(request), "body": body})
        if team is None:
            return JSONResponse({"message": "Unauthorized", "http_status_code": 401}, status_code=401)
        limit = self.budget[team]
        long = body.get("max_tokens", 0) >= 200
        held = self.spent[team] + (self.FIRST if not self.asked[team] else self.LONG if long else self.SHORT)
        self.asked[team] += 1
        tx = gateway_ids("ws", next(self.ids))
        if held > limit:
            return JSONResponse(
                {"message": f"Cost budget exceeded! Limit is ${limit / 1e6:.2f} per 60 minutes. Current spend: ${held / 1e6:.5f}.",
                 "http_status_code": 429},
                status_code=429,
                headers={**tx, **self._cost(team, 0)},
            )
        lite = self.controls.router and held * 2 >= limit
        self.spent[team] += self.LITE if lite else self.LONG if long else self.SHORT
        return JSONResponse(
            {
                "model": "qwen3:0.6b" if lite else "qwen3:1.7b",
                "usage": {"prompt_tokens": 30, "completion_tokens": 400, "total_tokens": 430},
                "choices": [{"message": {"content": "A team answer."}}],
            },
            headers={**tx, **self._cost(team, limit - held)},
        )

    def _cost(self, team: str, remaining: int) -> dict[str, str]:
        return {
            "x-cost-rate-limit-limit": str(self.budget[team]),
            "x-cost-rate-limit-remaining": str(max(0, remaining)),
            "x-cost-rate-limit-reset": str(int(time.time() * 1000) + 49 * 60_000),   # the period ends in 49 minutes
        }


class FakeApim:
    """The APIM management API: the AI workspace and its users, the APIs (by name, for the ids of the evidence), the logs, traces and decisions the console
    holds, the Agent Identity list, dashboards and analytics."""

    def __init__(self, workspace: FakeWorkspace, clock=time.time) -> None:
        self.workspace, self.log, self.auth, self.clock = workspace, [], [], clock
        self.workspace_exists = True
        self.deployment_state = "DEPLOYED"          # of the AI workspace, which is the API behind it
        self.down: set[str] = set()                 # what answers 503: llm, mcp, teams
        self.page_for_errors = ""                   # when set, a 503 answers this text (a page with a stack and an internal host) and not JSON
        self.searches: list[dict] = []                            # the searches of the logs that were not for a decision (the evidence reads an entry by its id: none)
        self.traces: list[dict] = []                              # what the console's Tracing holds: traceId, apiId, startTimeEpochMs, spans
        self.trace_reads: list[str] = []                          # the traceId of every read of one trace
        self.trace_searches: list[dict] = []
        self.gateway_logs: dict[str, dict] = {}                   # the log entry of each gateway request the console holds, by request id (`record`)
        self.log_reads: list[tuple[str, str | None]] = []         # (request id, apiId) of every read of one log entry
        self.delay = 0.0                                          # seconds the console takes to answer a read of an entry, a trace or a search
        self.decisions: list[dict] = []                           # the records of the policy engine, as the console's search gives them (`decide`)
        self.decision_searches: list[dict] = []
        self.search_filters = True                                # the search keeps to the request it was asked for (a test can make it answer with whatever it holds)
        self.gone: set[str] = set()                               # the ids of APIs that were deleted (a re-seed made them again with another id)
        self.apis = [{"id": "44ab2daf-d0e3-362c-8d88-2d741faf7eab", "name": "ACME Bank MCP", "type": "MCP_PROXY"},
                     {"id": "4b8dd261-28b5-4bb1-8dd2-6128b5cbb1f7", "name": "ACME Bank Teams", "type": "LLM_PROXY"}]
        self.agents = [{"id": "a-1", "name": "Ace"}]
        self.link = {"baseUrl": "http://am-management", "hasAccessToken": True, "environmentId": "DEFAULT",
                     "defaultDomainId": "dom-1", "defaultDomainHrid": "acme-bank"}
        self.identity_status = 200
        self.dashboards = [{"id": "d-1", "title": "ACME Bank - AI spend and safety"}]
        self.requests_last_hour = 42

    def app(self) -> Starlette:
        modules = "/gamma/organizations/DEFAULT/environments/DEFAULT/modules/aim"
        observability = "/gamma/organizations/DEFAULT/environments/DEFAULT/observability"
        return Starlette(
            routes=[
                Route("/management/organizations/DEFAULT/users", self.users),
                Route(f"{modules}/ai-workspaces", self.workspaces),
                Route(f"{modules}/ai-workspaces/ws-1", self.workspace_one),
                Route(f"{modules}/ai-workspaces/ws-1/users", self.members),
                Route(f"{observability}/logs/search", self.logs_search, methods=["POST"]),
                Route(f"{observability}/traces/search", self.traces_search, methods=["POST"]),
                Route(f"{observability}/traces/{{trace_id}}", self.trace_detail),
                Route(f"{observability}/logs/{{request_id}}", self.log_detail),
                Route("/management/v2/organizations/DEFAULT/environments/DEFAULT/apis", self.apis_list),
                Route("/management/v2/organizations/DEFAULT/environments/DEFAULT/apis/{api_id}", self.api_one),
                Route(f"{modules}/ai-workspaces/ws-1/users/{{sub}}/api-key", self.api_key),
                Route(f"{modules}/identity/am-config", self.am_config),
                Route(f"{modules}/identity/environments/{{env}}/domains/{{domain}}/agents", self.identity),
                Route(f"{observability}/dashboards", self.dashboards_list),
                Route(f"{observability}/analytics/measures", self.measures, methods=["POST"]),
            ]
        )

    def _refused(self, request: Request) -> Response | None:
        self.log.append(request.url.path)
        self.auth.append(request.headers.get("authorization"))
        known = basic(request) == ADMIN or request.headers.get("authorization") == f"Bearer {TOKEN}"
        return None if known else JSONResponse({"message": "Unauthorized"}, status_code=401)

    async def users(self, request: Request) -> Response:
        if refused := self._refused(request):
            return refused
        q = request.query_params["q"]
        data = [{"id": TEAM_USERS[q], "source": "gravitee", "sourceId": q}] if q in TEAM_USERS else []
        return JSONResponse({"data": data})

    async def workspaces(self, request: Request) -> Response:
        found = [{"id": "ws-1", "name": "ACME Bank Teams"}] if self.workspace_exists else []
        return self._refused(request) or JSONResponse({"content": found, "totalElements": len(found)})

    async def workspace_one(self, request: Request) -> Response:
        return self._refused(request) or JSONResponse(
            {"id": "ws-1", "name": "ACME Bank Teams", "contextPath": "/acme-bank-teams", "assetIds": [TEAMS_API],
             "deploymentState": self.deployment_state}
        )

    def record(self, request_id: str, api_id: str, started: int, status: int | None = 200, **fields: Any) -> dict:
        """The console now holds the log entry of a gateway request (`status` None: the first second, when only the ids are written)."""
        entry = {"requestId": request_id, "apiId": api_id, "timestampEpochMs": started, "status": status, "uri": "/acme-bank", **fields}
        self.gateway_logs[request_id] = entry
        return entry

    def decide(self, request_id: str, event_id: str, api_id: str = MCP_API, decision: str = "FORBID") -> dict:
        """The policy engine decided a request: the record of its decision, as the console's search gives it."""
        record = {"apiId": api_id, "requestId": request_id, "timestampEpochMs": 1,
                  "authz": {"eventId": event_id, "decision": decision, "reasons": ["Forbidden by policy 'Customers use only their own accounts'"]}}
        self.decisions.append(record)
        return record

    async def logs_search(self, request: Request) -> Response:
        if refused := self._refused(request):
            return refused
        body = await request.json()
        if any(f.get("name") == "RECORD_TYPE" for f in body.get("filters", [])):
            self.decision_searches.append({"body": body, "query": dict(request.query_params)})
            wanted = next(f["value"] for f in body["filters"] if f["name"] == "REQUEST_ID")
            return JSONResponse({"data": [d for d in self.decisions if not self.search_filters or not isinstance(d, dict) or d.get("requestId") == wanted]})
        self.searches.append({"body": body, "query": dict(request.query_params)})
        return JSONResponse({"data": []})

    async def traces_search(self, request: Request) -> Response:
        if refused := self._refused(request):
            return refused
        body = await request.json()
        self.trace_searches.append({"body": body, "query": dict(request.query_params)})
        mine = [t for t in self.traces if t["apiId"] == body["apiId"]]
        return JSONResponse({"data": [{k: t[k] for k in ("traceId", "startTimeEpochMs")} for t in mine]})

    async def trace_detail(self, request: Request) -> Response:
        if refused := self._refused(request):
            return refused
        await asyncio.sleep(self.delay)
        self.trace_reads.append(request.path_params["trace_id"])
        found = next((t for t in self.traces if t["traceId"] == request.path_params["trace_id"] and t["apiId"] == request.query_params["apiId"]), None)
        return JSONResponse(found) if found else JSONResponse({"message": "Not found"}, status_code=404)

    async def log_detail(self, request: Request) -> Response:
        if refused := self._refused(request):
            return refused
        await asyncio.sleep(self.delay)
        found, api_id = request.path_params["request_id"], request.query_params.get("apiId")
        self.log_reads.append((found, api_id))
        if api_id is None:      # the console needs the API of the request, and says so
            return JSONResponse({"message": "Required scope dimension 'apiId' is missing", "http_status": 400}, status_code=400)
        if found in self.gateway_logs:
            entry = self.gateway_logs[found]
            return JSONResponse(entry) if entry["apiId"] == api_id else JSONResponse({"message": "Log not found", "http_status": 404}, status_code=404)
        return JSONResponse({"message": "Log not found", "http_status": 404}, status_code=404)

    async def apis_list(self, request: Request) -> Response:
        q = request.query_params.get("q", "")
        return self._refused(request) or JSONResponse({"data": [a for a in self.apis if q in a["name"]]})

    async def api_one(self, request: Request) -> Response:
        """The APIM v2 entity of an API, which the app reads to know whether the one it named is still there (a re-seed makes the MCP proxy and the workspace's own again)."""
        if refused := self._refused(request):
            return refused
        api_id = request.path_params["api_id"]
        key = {LLM_API: "llm", MCP_API: "mcp", TEAMS_API: "teams"}.get(api_id)
        made = next((a for a in self.apis if a["id"] == api_id and a["id"] not in self.gone), None)
        if made is not None and key is None:
            return JSONResponse({"id": made["id"], "name": made["name"]})      # an API made again: it is there, and it is none of the three the story knows
        if key is None or api_id in self.gone:
            return JSONResponse({"message": "Not found"}, status_code=404)
        if key in self.down:
            if self.page_for_errors:
                return Response(self.page_for_errors, status_code=503, media_type="text/html")
            return JSONResponse({"message": "Service unavailable"}, status_code=503)
        return JSONResponse({"id": api_id, "name": {"llm": "ACME Bank LLM", "mcp": "ACME Bank MCP", "teams": "ACME Bank Teams"}[key]})

    async def members(self, request: Request) -> Response:
        return self._refused(request) or JSONResponse(
            {"data": [{"subscriptionId": f"s-{user}", "userId": user} for user in TEAM_USERS.values()]}
        )

    async def api_key(self, request: Request) -> Response:
        if refused := self._refused(request):
            return refused
        user = request.path_params["sub"][2:]
        team = next(team for team, u in TEAM_USERS.items() if u == user)
        return JSONResponse({"apiKey": self.workspace.keys[team]})

    async def am_config(self, request: Request) -> Response:
        return self._refused(request) or JSONResponse(self.link)

    async def identity(self, request: Request) -> Response:
        """The agents of the domain Gamma is linked to; a path with any other domain is not a route of Gamma."""
        if refused := self._refused(request):
            return refused
        if self.identity_status != 200:
            return JSONResponse({"code": "am_not_configured"}, status_code=self.identity_status)
        if (request.path_params["env"], request.path_params["domain"]) != (
            self.link["environmentId"], self.link["defaultDomainId"]
        ):
            return JSONResponse({"message": "HTTP 404 Not Found"}, status_code=404)
        return JSONResponse({"items": self.agents, "total": len(self.agents)})

    async def dashboards_list(self, request: Request) -> Response:
        return self._refused(request) or JSONResponse({"data": self.dashboards})

    async def measures(self, request: Request) -> Response:
        return self._refused(request) or JSONResponse(
            {
                "metrics": [
                    {"name": "HTTP_REQUESTS", "measures": [{"name": "COUNT", "value": float(self.requests_last_hour)}]}
                ]
            }
        )


class FakeTraffic:
    def __init__(self) -> None:
        self.paused, self.resets = False, 0

    async def status(self, request: Request) -> Response:
        return JSONResponse({"paused": self.paused, "calls": 12, "errors": 0, "last": {"scenario": "balance"}})

    async def pause(self, request: Request) -> Response:
        self.paused = True
        return JSONResponse({"paused": True})

    async def resume(self, request: Request) -> Response:
        self.paused = False
        return JSONResponse({"paused": False})

    async def reset(self, request: Request) -> Response:
        self.resets += 1
        return JSONResponse({"reset": True})

    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/status", self.status),
                Route("/pause", self.pause, methods=["POST"]),
                Route("/resume", self.resume, methods=["POST"]),
                Route("/reset", self.reset, methods=["POST"]),
            ]
        )


class Routed(httpx.AsyncBaseTransport):
    """Sends each request to the fake that plays its host."""

    def __init__(self, hosts: dict[str, Any]) -> None:
        self.hosts = {host: httpx.ASGITransport(app=app) for host, app in hosts.items()}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host not in self.hosts:
            raise httpx.ConnectError(f"no fake plays {request.url.host}")
        return await self.hosts[request.url.host].handle_async_request(request)


class World:
    def __init__(self) -> None:
        ids = itertools.count(1)
        self.controls = Controls()
        self.am, self.ace = FakeAm(), FakeAce(controls=self.controls)
        self.direct_ace = FakeAce(protected=False, controls=self.controls)
        self.llm, self.workspace = FakeLlm(ids, self.controls), FakeWorkspace(ids, self.controls)
        self.mcp = FakeMcp(ids, controls=self.controls)
        self.bank, self.traffic = FakeBank(), FakeTraffic()
        self.now = time.time()                     # the clock of the test: a protection deployed "just now" is read against it
        self.apim = FakeApim(self.workspace, clock=lambda: self.now)
        self.gateway_ace = Behind(ace_app(self.ace, "http://gateway.test/acme-bank/ace/"), "tx-a2a", ids)
        gateway = Starlette(
            routes=[
                Mount("/acme-bank/ace", app=self.gateway_ace),
                *self.llm.routes(),
                *self.workspace.routes(),
                Mount("/", app=self.mcp.app()),
            ]
        )
        self.transport = Routed(
            {
                "am.test": self.am.app(),
                "gateway.test": gateway,
                "ace-direct.test": ace_app(self.direct_ace, "http://ace-direct.test/"),
                "bank-mcp.test": self.bank.app(),
                "apim.test": self.apim.app(),
                "traffic.test": self.traffic.app(),
            }
        )

    def settings(self, **overrides: Any) -> Settings:
        values = dict(
            web_client_secret=CLIENT[1],
            demo_password=DEMO_PASSWORD,
            am_token_url="http://am.test/acme-bank/oauth/token",
            am_authorize_url="http://am.test/acme-bank/oauth/authorize",
            ace_url="http://gateway.test/acme-bank/ace/",
            ace_direct_url="http://ace-direct.test/",
            mcp_url="http://gateway.test/acme-bank/mcp",
            mcp_direct_url="http://bank-mcp.test/",
            llm_url="http://gateway.test/acme-bank/llm",
            gateway_url="http://gateway.test",
            dev_llm_api_key=DEV_KEY,
            admin_token=ADMIN_TOKEN,
            apim_management_url="http://apim.test",
            apim_username=ADMIN[0],
            apim_password=ADMIN[1],
            gamma_url="http://gamma.test",
            traffic_url="http://traffic.test",
        )
        return Settings(**{**values, **overrides})

    def clients(self) -> Clients:
        """One client for every role: the transport plays all the services."""
        client = httpx.AsyncClient(transport=self.transport, timeout=30)
        return Clients(am=client, a2a=client, gateway=client, gamma=client, internal=client)
