"""A fake platform for the tests: AM, the gateway's APIs, the AI workspace, Gamma and Ace, in one ASGI app, so the
generator's real SDK clients run against it with no socket.

The gateway's policies are the behavior matrix of the playground written as one function, `permitted`. Ace
is a keyword router over the same tools; a test that needs it to misbehave replaces `platform.ace_script`.
"""
import asyncio
import base64
import contextlib
import json
import random
import re
import time
from typing import Annotated, Any, Callable
from urllib.parse import parse_qsl

import httpx
import httpx2
from a2a.helpers import new_data_part, new_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ledger import cost_usd
from runner import Pace
from server import assemble
from settings import Settings

ENV = {"GATEWAY_URL": "http://gateway", "AM_TOKEN_URL": "http://am/acme-bank/oauth/token",
       "APIM_MANAGEMENT_URL": "http://apim", "APIM_USERNAME": "admin", "APIM_PASSWORD": "admin",
       "BANK_DEMO_PASSWORD": "demo-password", "TRAFFIC_CLIENT_SECRET": "traffic-secret", "TRAFFIC_LLM_API_KEY": "traffic-key"}
PASSWORD, TRAFFIC_KEY = ENV["BANK_DEMO_PASSWORD"], ENV["TRAFFIC_LLM_API_KEY"]

USERS = {"alice": {"role": "customer", "customer_id": "C-1001", "accounts": ["ACC-1001", "ACC-1002"]},
         "bob": {"role": "customer", "customer_id": "C-2001", "accounts": ["ACC-2001"]},
         "tina": {"role": "teller", "customer_id": None, "accounts": []}}
OWNERS = {"ACC-1001": "C-1001", "ACC-1002": "C-1001", "ACC-2001": "C-2001", "ACC-9001": "C-9001"}
PUBLIC = ("get_exchange_rate", "simulate_loan", "find_branches")
DENIAL = {"message": "Not allowed by ACME authorization policy", "http_status_code": 403}
GUARD = {"message": "AI prompt validation detected. Reason: [MALICIOUS]", "http_status_code": 400}
BUDGETS = {"team-care": 5.00, "team-fraud": 2.00, "team-hackathon": 0.10}
Amount = Annotated[float, Field(strict=True, gt=0)]       # a JSON number above zero, as in the bank's tools


def settings(**env: str) -> Settings:
    return Settings.from_env({**ENV, **env})


def permitted(who: str, tool: str, args: dict[str, Any], via_agent: bool = False) -> bool:
    """The behavior matrix as the policies decide it."""
    user = USERS[who]
    if tool in PUBLIC:
        return True
    if tool == "freeze_card":
        return user["role"] == "teller"
    if tool == "transfer_funds":
        amount = args.get("amount")
        if user["role"] != "customer" or args.get("from_account") not in user["accounts"]:
            return False
        return isinstance(amount, (int, float)) and 1 <= amount <= (500 if via_agent else 10000)
    if user["role"] == "teller":
        return True
    if tool == "list_accounts":
        return args.get("customer_id") == user["customer_id"]
    return args.get("account_id") in user["accounts"]


class Bank:
    """The bank's data behind the tools."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.balances = {"ACC-1001": 4820.55, "ACC-1002": 15300.0, "ACC-2001": 920.10, "ACC-9001": 25000.0}
        self.cards = {"CARD-1001": "ACTIVE", "CARD-2001": "ACTIVE", "CARD-9001": "ACTIVE"}

    def list_accounts(self, customer_id: str) -> dict:
        return {"customer_id": customer_id, "accounts": [{"account_id": a, "balance": b}
                                                         for a, b in self.balances.items() if OWNERS[a] == customer_id]}

    def get_balance(self, account_id: str) -> dict:
        return {"account_id": account_id, "balance": self.balances[account_id]}

    def transfer(self, source: str, target: str, amount: float) -> dict:
        if self.balances[source] < amount:
            raise ToolError("Insufficient funds")
        self.balances[source] = round(self.balances[source] - amount, 2)
        self.balances[target] = round(self.balances[target] + amount, 2)
        return {"from_account": source, "to_account": target, "amount": amount}

    def freeze(self, card_id: str) -> dict:
        self.cards[card_id] = "FROZEN"
        return {"card_id": card_id, "status": "FROZEN"}


def tool_server(bank: Bank, teller: bool) -> MCPServer:
    """The bank's MCP server; the proxy's mcp-acl shows a customer one tool fewer, so there are two of them."""
    server = MCPServer("ACME Bank MCP")

    @server.tool()
    def list_accounts(customer_id: str) -> dict:
        return bank.list_accounts(customer_id)

    @server.tool()
    def get_balance(account_id: str) -> dict:
        return bank.get_balance(account_id)

    @server.tool()
    def list_transactions(account_id: str, limit: int = 10) -> dict:
        return {"account_id": account_id, "count": 0, "total": 0, "transactions": []}

    @server.tool()
    def transfer_funds(from_account: str, to_account: str, amount: Amount, reference: str = "") -> dict:
        return bank.transfer(from_account, to_account, amount)

    @server.tool()
    def get_exchange_rate(base: str, quote: str, amount: Amount) -> dict:
        return {"base": base, "quote": quote, "rate": 1.08, "converted": round(amount * 1.08, 2)}

    @server.tool()
    def simulate_loan(amount: float, years: int, annual_rate_percent: float = 4.2) -> dict:
        return {"monthly_payment": 368.0}

    @server.tool()
    def find_branches(city: str) -> dict:
        return {"branches": [{"city": city}]}

    if teller:
        @server.tool()
        def freeze_card(card_id: str, reason: str = "") -> dict:
            return bank.freeze(card_id)
    return server


# --- Ace -------------------------------------------------------------------------------------------------------

SENTENCES = [  # (what the user wrote, the tool Ace calls, how it builds the arguments)
    (r"Send (\d+) EUR from (ACC-\d+) to (ACC-\d+)", "transfer_funds",
     lambda who, m: {"from_account": m[2], "to_account": m[3], "amount": int(m[1])}),
    (r"Freeze (CARD-\d+)", "freeze_card", lambda who, m: {"card_id": m[1], "reason": "reported lost"}),
    (r"accounts of customer (C-\d+)", "list_accounts", lambda who, m: {"customer_id": m[1]}),
    (r"(?i)show my accounts", "list_accounts", lambda who, m: {"customer_id": USERS[who]["customer_id"]}),
    (r"transactions on (ACC-\d+)", "list_transactions", lambda who, m: {"account_id": m[1], "limit": 5}),
    (r"balance (?:on|of) (ACC-\d+)", "get_balance", lambda who, m: {"account_id": m[1]}),
    (r"Convert", "get_exchange_rate", lambda who, m: {"base": "EUR", "quote": "USD", "amount": 100}),
    (r"loan", "simulate_loan", lambda who, m: {"amount": 20000, "years": 5}),
    (r"branches", "find_branches", lambda who, m: {"city": "Paris"}),
]


class FakeAce(AgentExecutor):
    def __init__(self, platform: "Platform") -> None:
        self.platform = platform

    async def execute(self, context, event_queue) -> None:
        bearer = context.call_context.state["headers"].get("authorization", "")[7:]
        answer, trace = self.platform.ace_script(self.platform.tokens[bearer], context.get_user_input())
        await event_queue.enqueue_event(new_message([new_text_part(answer), new_data_part({"trace": trace})],
                                                    context_id=context.context_id))

    async def cancel(self, context, event_queue) -> None:
        raise NotImplementedError


def llm_row(detail: str = "900 tokens, 1 tool call(s)", outcome: str = "ok", status: int = 200) -> dict:
    return {"step": "llm", "name": "acme-chat", "outcome": outcome, "detail": detail, "ms": 40, "status": status}


# --- The platform ----------------------------------------------------------------------------------------------

class Platform:
    """Use it as `async with Platform() as platform`: the two MCP servers need their lifespan to run."""

    def __init__(self) -> None:
        self.bank = Bank()
        self.calls: list[dict[str, Any]] = []            # every request: path, method, user agent, who
        self.tool_calls: list[tuple[str | None, str, dict]] = []     # each tools/call: who, tool, arguments
        self.tokens: dict[str, str] = {}                 # token -> person
        self.revoked: set[str] = set()
        self.signed_in = 0
        self.workspace_state = "DEPLOYED"
        self.workspace_exists = True
        self.team_keys = {"team-care": "key-care", "team-fraud": "key-fraud", "team-hackathon": "key-hackathon"}
        self.stale_keys: dict[str, str] = {}              # what Gamma answers when it is not what the gateway accepts
        self.spent = {team: 0.0 for team in BUDGETS}
        self.bodies: list[tuple[str, dict]] = []         # what each completion asked for: (who, request body)
        self.llm_tokens: list[tuple[float, int]] = []
        self.cached: set[str] = set()
        self.cache_on = True
        self.guard_on = True                             # the LLM proxy's guard rails: off is where the lessons start
        self.answer_tokens = (30, 40)                    # prompt and completion tokens of an answer
        self.ace_script: Callable[[str, str], tuple[str, list]] = self.ace_turn
        self.down = False                                # the gateway answers 503 to everything it serves
        self.mcp_limited = False                         # the MCP proxy answers 429 to every tool call
        self.mcp_delay = 0.0                             # seconds the MCP proxy takes before it answers
        # a person whose transfers the gateway fails: True when the bank has moved the money by then, False when not
        self.broken_transfers: dict[str, bool] = {}
        self._mcp = {False: tool_server(self.bank, False), True: tool_server(self.bank, True)}
        self._mcp_apps = {teller: server.streamable_http_app(streamable_http_path="/", stateless_http=True,
                                                             json_response=True, host="0.0.0.0")
                          for teller, server in self._mcp.items()}
        self._stack = contextlib.AsyncExitStack()
        self.app = self._router({"/acme-bank/oauth": self._am(), "/acme-bank/llm": self._llm(),
                                 "/acme-bank-teams": self._teams(), "/gamma": self._gamma(),
                                 "/management": self._management(), "/acme-bank/mcp": self._mcp_gateway,
                                 "/acme-bank/ace": self._ace_gateway()})

    async def __aenter__(self) -> "Platform":
        for app in self._mcp_apps.values():
            await self._stack.enter_async_context(app.router.lifespan_context(app))
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()

    def transports(self) -> tuple[httpx.AsyncBaseTransport, httpx2.AsyncBaseTransport]:
        return httpx.ASGITransport(app=self.app), httpx2.ASGITransport(app=self.app)

    # What the tests ask about

    def who(self, authorization: str) -> str | None:
        token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
        return None if token in self.revoked else self.tokens.get(token)

    def seen(self, prefix: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["path"].startswith(prefix)]

    def revoke_every_token(self) -> None:
        self.revoked.update(self.tokens)

    # The router: a gateway strips its context path before it reaches the upstream

    def _router(self, routes: dict[str, Callable]):
        async def app(scope, receive, send) -> None:
            path = scope["path"]
            ordered = sorted(routes, key=len, reverse=True)
            prefix = next((p for p in ordered if path == p or path.startswith(p + "/")), None)
            if prefix is None:
                return await JSONResponse({"message": "No context-path matches the request URI.",
                                           "http_status_code": 404}, 404)(scope, receive, send)
            headers = {k.decode(): v.decode() for k, v in scope["headers"]}
            self.calls.append({"path": path, "query": scope["query_string"].decode(), "method": scope["method"],
                               "agent": headers.get("user-agent"), "who": self.who(headers.get("authorization", "")),
                               "headers": headers})
            if self.down and not path.startswith(("/gamma", "/management", "/acme-bank/oauth")):
                return await JSONResponse({"message": "Service unavailable"}, 503)(scope, receive, send)
            inner = path[len(prefix):] or "/"
            await routes[prefix](dict(scope, path=inner, raw_path=inner.encode()), receive, send)
        return app

    # AM

    def _am(self) -> Starlette:
        async def token(request: Request) -> Response:
            form = dict(parse_qsl((await request.body()).decode()))
            basic = base64.b64decode(request.headers.get("authorization", "Basic ")[6:]).decode()
            if basic != f"acme-bank-traffic:{ENV['TRAFFIC_CLIENT_SECRET']}" or form.get("password") != PASSWORD:
                return JSONResponse({"error": "invalid_grant", "error_description": "Bad credentials"}, 401)
            who = form["username"].split("@")[0]
            self.signed_in += 1
            access = f"token-{who}-{self.signed_in}"
            self.tokens[access] = who
            return JSONResponse({"access_token": access, "token_type": "bearer", "expires_in": 7200})
        return Starlette(routes=[Route("/token", token, methods=["POST"])])

    # The LLM proxy, with the Traffic plan and the semantic cache of the Developers plan

    def _llm(self) -> Starlette:
        def refused(request: Request) -> Response | None:
            if request.headers.get("authorization") != f"Bearer {TRAFFIC_KEY}":
                return JSONResponse({"message": "Unauthorized", "http_status_code": 401}, 401)
            return None

        async def models(request: Request) -> Response:
            return refused(request) or JSONResponse({"object": "list", "data": [{"id": "acme-chat", "object": "model"}]})

        async def completions(request: Request) -> Response:
            if (denied := refused(request)) is not None:
                return denied
            body = await request.json()
            self.bodies.append(("traffic", body))
            question = body["messages"][-1]["content"]
            if "Ignore all previous instructions" in question and self.guard_on:
                return JSONResponse(GUARD, 400)
            now = time.time()
            used = sum(tokens for at, tokens in self.llm_tokens if now - at < 60)
            if used >= 3000:
                return JSONResponse({"message": "Rate limit exceeded! You reached the limit of 3000 tokens per 1 minutes",
                                     "http_status_code": 429}, 429,
                                    headers={"X-Token-Rate-Limit-Reset": str(int((now + 30) * 1000))})
            if self.cache_on and question in self.cached:
                return JSONResponse(completion("A cached answer.", (0, 0), "resp_llmproxy"))
            self.cached.add(question)
            tokens = sum(self.answer_tokens)
            self.llm_tokens.append((now, tokens))
            headers = {"X-Token-Rate-Limit-Limit": "3000", "X-Token-Rate-Limit-Remaining": str(3000 - used - tokens),
                       "X-Token-Rate-Limit-Reset": str(int((now + 60) * 1000))}
            return JSONResponse(completion("A short answer.", self.answer_tokens), headers=headers)
        return Starlette(routes=[Route("/models", models), Route("/chat/completions", completions, methods=["POST"])])

    # The AI workspace: a key per team, a budget per team, the router that moves a team to the small model at half

    def _teams(self) -> Starlette:
        def team_of(request: Request) -> str | None:
            key = request.headers.get("authorization", "").removeprefix("Bearer ")   # as the gateway reads it
            return next((team for team, own in self.team_keys.items() if own == key), None)

        async def models(request: Request) -> Response:
            if team_of(request) is None:
                return JSONResponse({"message": "Unauthorized", "http_status_code": 401}, 401)
            return JSONResponse({"object": "list", "data": [{"id": "smart", "object": "model"}]})

        async def completions(request: Request) -> Response:
            team = team_of(request)
            if team is None:
                return JSONResponse({"message": "Unauthorized", "http_status_code": 401}, 401)
            self.bodies.append((team, await request.json()))
            limit = BUDGETS[team]
            if self.spent[team] >= limit:
                return JSONResponse({"message": f"Cost budget exceeded! Limit is ${limit:.2f} per 1440 minutes.",
                                     "http_status_code": 429}, 429,
                                    headers={"X-Cost-Rate-Limit-Reset": str(int((time.time() + 600) * 1000))})
            model = "lite" if self.spent[team] > limit / 2 else "smart"
            self.spent[team] += cost_usd(model, *self.answer_tokens)
            headers = {"X-Cost-Rate-Limit-Limit": str(int(limit * 1e6)),
                       "X-Cost-Rate-Limit-Remaining": str(int((limit - self.spent[team]) * 1e6)),
                       "X-Cost-Rate-Limit-Reset": str(int((time.time() + 3600) * 1000))}
            return JSONResponse(completion("A team answer.", self.answer_tokens, model=model), headers=headers)
        return Starlette(routes=[Route("/models", models), Route("/chat/completions", completions, methods=["POST"])])

    # Gamma and the management API

    def _gamma(self) -> Starlette:
        base = "/organizations/DEFAULT/environments/DEFAULT/modules/aim/ai-workspaces"

        async def workspaces(request: Request) -> Response:
            if int(request.query_params.get("page", "1")) < 1:
                return JSONResponse({"message": "Pagination page param must be >= 1"}, status_code=400)
            found = [{"id": "ws-1", "name": "ACME Bank Teams", "deploymentState": self.workspace_state}] if self.workspace_exists else []
            return JSONResponse({"data": found, "pagination": {"page": 1, "perPage": 100, "totalCount": len(found)}})

        async def workspace(request: Request) -> Response:
            return JSONResponse({"id": "ws-1", "name": "ACME Bank Teams", "contextPath": "/acme-bank-teams"})

        async def members(request: Request) -> Response:
            data = [{"subscriptionId": f"sub-{team}", "userId": f"user-{team}", "budgetId": "b-1", "status": "ACTIVE"}
                    for team in self.team_keys]
            return JSONResponse({"data": data, "pagination": {"page": 1, "perPage": 100, "totalCount": len(data)}})

        async def api_key(request: Request) -> Response:
            team = request.path_params["subscription"][4:]
            return JSONResponse({"apiKey": self.stale_keys.get(team, self.team_keys[team])})

        guarded = self._admin_only
        return Starlette(routes=[
            Route(base, guarded(workspaces)), Route(base + "/ws-1", guarded(workspace)),
            Route(base + "/ws-1/users", guarded(members)),
            Route(base + "/ws-1/users/{subscription}/api-key", guarded(api_key))])

    def _management(self) -> Starlette:
        async def users(request: Request) -> Response:
            team = request.query_params["q"]
            return JSONResponse({"data": [{"id": f"user-{team}", "source": "gravitee", "sourceId": team}]})
        return Starlette(routes=[Route("/organizations/DEFAULT/users", self._admin_only(users))])

    @staticmethod
    def _admin_only(handler: Callable) -> Callable:
        async def guarded(request: Request) -> Response:
            if request.headers.get("authorization") != "Basic " + base64.b64encode(b"admin:admin").decode():
                return JSONResponse({"message": "Unauthorized"}, 401)
            return await handler(request)
        return guarded

    # The MCP proxy: the sign-in plan, then the authorization policies, then the bank's server

    async def _mcp_gateway(self, scope, receive, send) -> None:
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        headers = {k.decode(): v.decode() for k, v in scope["headers"]}
        who = self.who(headers.get("authorization", ""))
        if who is None:
            return await JSONResponse({"message": "Unauthorized", "http_status_code": 401}, 401)(scope, receive, send)
        request = json.loads(body or b"{}")
        await asyncio.sleep(self.mcp_delay)
        if request.get("method") == "tools/call" and self.mcp_limited:
            limit = {"message": "Rate limit exceeded! You reached the limit of 30 requests per 1 minutes",
                     "http_status_code": 429}
            return await JSONResponse(limit, 429)(scope, receive, send)
        if request.get("method") == "tools/call":
            params = request["params"]
            self.tool_calls.append((who, params["name"], params.get("arguments", {})))
            if not permitted(who, params["name"], params.get("arguments", {})):
                return await JSONResponse(DENIAL, 403)(scope, receive, send)
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        app = self._mcp_apps[USERS[who]["role"] == "teller"]
        if request.get("method") == "tools/call" and request["params"]["name"] == "transfer_funds" \
                and who in self.broken_transfers:
            return await self._give_up(app, scope, replay, receive, send, self.broken_transfers[who])
        await app(scope, replay, send)

    async def _give_up(self, app, scope, replay, receive, send, after_the_bank_moved_it: bool) -> None:
        """The gateway fails a transfer: after the bank did it, so the answer is lost, or before it reached the bank."""
        if after_the_bank_moved_it:
            async def lost(message) -> None:
                return None
            await app(scope, replay, lost)
        status = 504 if after_the_bank_moved_it else 503
        await JSONResponse({"message": "Gateway timeout", "http_status_code": status}, status)(scope, receive, send)

    # Ace behind the A2A proxy

    def _ace_gateway(self) -> Callable:
        card = AgentCard(name="Ace", description="ACME Bank's assistant", version="1.0.0",
                         supported_interfaces=[AgentInterface(url="http://gateway/acme-bank/ace/",
                                                              protocol_binding="JSONRPC", protocol_version="1.0")],
                         capabilities=AgentCapabilities(streaming=False), default_input_modes=["text/plain"],
                         default_output_modes=["text/plain"], skills=[])
        handler = DefaultRequestHandler(agent_executor=FakeAce(self), task_store=InMemoryTaskStore(), agent_card=card)
        ace = Starlette(routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, rpc_url="/")])

        async def gateway(scope, receive, send) -> None:
            headers = {k.decode(): v.decode() for k, v in scope["headers"]}
            if self.who(headers.get("authorization", "")) is None:
                refused = JSONResponse({"message": "Unauthorized", "http_status_code": 401}, 401)
                return await refused(scope, receive, send)
            await ace(scope, receive, send)
        return gateway

    def ace_turn(self, who: str, text: str) -> tuple[str, list]:
        """What Ace does: one model call that picks a tool by the words of the question, the tool through the
        policies as the agent acting for the user, and the answer."""
        if "Ignore all previous instructions" in text:
            return ("I can't help with that: the request was blocked by ACME's AI policy.",
                    [llm_row(GUARD["message"], "blocked", 400)])
        for pattern, tool, arguments in SENTENCES:
            found = re.search(pattern, text)
            if found:
                args = arguments(who, found)
                allowed = permitted(who, tool, args, via_agent=True)
                outcome, status, detail = ("ok", 200, "done") if allowed else ("denied", 403, DENIAL["message"])
                if allowed and tool == "transfer_funds":
                    self.bank.transfer(args["from_account"], args["to_account"], args["amount"])
                if allowed and tool == "freeze_card":
                    self.bank.freeze(args["card_id"])
                return (f"{tool}: {outcome}",
                        [llm_row(), {"step": "tool", "name": tool, "arguments": args, "outcome": outcome,
                                     "detail": detail, "ms": 12, "status": status, "transaction_id": "tx-1"},
                         llm_row("700 tokens, 0 tool call(s)")])
        return "Hello, how can I help?", [llm_row("500 tokens, 0 tool call(s)")]


def completion(text: str, tokens: tuple[int, int], answer_id: str = "chatcmpl-1", model: str = "qwen3:1.7b") -> dict:
    return {"id": answer_id, "object": "chat.completion", "created": 1, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1], "total_tokens": sum(tokens)}}


class Clock:
    """A clock the tests move: sleeping advances it and takes no time."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
        await asyncio.sleep(0)         # a real sleep lets the other tasks run


@contextlib.asynccontextmanager
async def generator(seed: int = 1, pace: Pace | None = None, **env: str):
    """The generator, wired to a fake platform and a clock of the test's own: yields (platform, runner, clock)."""
    async with Platform() as platform:
        clock = Clock()
        runner, close = assemble(settings(**env), *platform.transports(), pace=pace or Pace(),
                                 rng=random.Random(seed), clock=clock, sleep=clock.sleep)
        try:
            yield platform, runner, clock
        finally:
            await close()
