"""The fakes that stand around Ace in the tests, in memory (no socket, no model, no platform).

  StubOpenAI   an OpenAI-compatible server that answers from a script and records what it was asked
  bank_server  a fake of the bank's MCP server: the tool names and argument shapes of the real one, no logic
  Gateway      what the MCP proxy does around it: checks the bearer, refuses a tool, stamps transaction ids
  StubAm       the token endpoint of Access Management, as far as Ace uses it
  World        all of it wired to an Ace, the way the containers are wired
"""
import asyncio
import base64
import contextlib
import json
from dataclasses import replace
from typing import Annotated, Any, AsyncIterator, Callable
from urllib.parse import parse_qsl

import httpx
import httpx2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from chat import Ace
from identity import ACCESS_TOKEN, TOKEN_EXCHANGE, Delegation
from llm import Llm
from settings import Settings

ALICE = {"username": "alice@acme-bank.test", "name": "Alice Martin", "role": "customer", "customer_id": "C-1001",
         "accounts": ["ACC-1001", "ACC-1002"], "sub": "alice-id"}
BOB = {"username": "bob@acme-bank.test", "name": "Bob Chen", "role": "customer", "customer_id": "C-2001",
       "accounts": ["ACC-2001"], "sub": "bob-id"}
TINA = {"username": "tina@acme-bank.test", "name": "Tina Torres", "role": "teller", "sub": "tina-id"}
AGENT_SECRET = "ace-secret"


def fake_jwt(**claims: Any) -> str:
    def part(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
    return f"{part({'alg': 'none'})}.{part(claims)}.signature"


def claims_of(token: str) -> dict[str, Any]:
    body = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def alice_token() -> str:
    return fake_jwt(**ALICE)


# ---- the model --------------------------------------------------------------------------------------------------------

def completion(content: str | None = None, tool_calls: list[dict[str, Any]] | None = None,
               tokens: int = 15) -> dict[str, Any]:
    """An OpenAI chat.completion body. A tool call's `arguments` is a dict, or a string to write it badly."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [
            {"id": f"call_{i}", "type": "function",
             "function": {"name": c["name"], "arguments": c["arguments"] if isinstance(c["arguments"], str)
                          else json.dumps(c["arguments"])}} for i, c in enumerate(tool_calls)]
    return {"id": "chatcmpl-stub", "object": "chat.completion", "created": 1, "model": "acme-chat",
            "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
            "usage": {"prompt_tokens": tokens - 5, "completion_tokens": 5, "total_tokens": tokens}}


def tool_call(name: str, **arguments: Any) -> dict[str, Any]:
    return completion(tool_calls=[{"name": name, "arguments": arguments}])


def refusal(status: int, message: str, **headers: str) -> Response:
    """The body a policy of the gateway answers with: not the OpenAI error shape."""
    return JSONResponse({"message": message, "http_status_code": status}, status_code=status, headers=headers)


def provider_error(status: int, message: str) -> Response:
    """The error body of a provider such as OpenAI or Ollama."""
    return JSONResponse({"error": {"message": message, "type": "invalid_request_error"}}, status_code=status)


class StubOpenAI:
    """Answers each call from the script, in order: a completion body, a Response, or a function of the request body."""

    def __init__(self, *script: Any) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    async def chat_completions(self, request: Request) -> Response:
        body = await request.json()
        self.requests.append({"headers": dict(request.headers), "body": body})
        if not self.script:
            return refusal(500, "nothing scripted")
        step = self.script.pop(0)
        step = step(body) if callable(step) and not isinstance(step, Response) else step
        # the gateway keeps a transaction id it is given, and makes one up otherwise
        stamp = {"X-Gravitee-Transaction-Id": request.headers.get("x-gravitee-transaction-id") or f"llm-{len(self.requests)}"}
        return step if isinstance(step, Response) else JSONResponse(step, headers=stamp)

    def app(self) -> Starlette:
        return Starlette(routes=[Route("/{prefix:path}/chat/completions", self.chat_completions, methods=["POST"]),
                                 Route("/chat/completions", self.chat_completions, methods=["POST"])])

    def asked(self, index: int) -> dict[str, Any]:
        return self.requests[index]["body"]


# ---- the bank ---------------------------------------------------------------------------------------------------------

Amount = Annotated[float, Field(strict=True, gt=0)]


def list_accounts(customer_id: str) -> dict[str, Any]:
    """List the accounts of a customer."""
    return {"customer_id": customer_id, "accounts": [{"account_id": "ACC-1001", "type": "checking", "currency": "EUR",
                                                      "balance": 4820.55}]}


def get_balance(account_id: str) -> dict[str, Any]:
    """Balance of one account."""
    if account_id != "ACC-1001":
        raise ToolError(f"Unknown account {account_id}")
    return {"account_id": account_id, "balance": 4820.55, "currency": "EUR"}


def list_transactions(account_id: str, limit: int = 10, category: str | None = None) -> dict[str, Any]:
    """Latest transactions of one account."""
    return {"account_id": account_id, "count": 1, "total": -12.5, "transactions": [{"id": "T-1", "amount": -12.5}]}


def transfer_funds(from_account: str, to_account: str, amount: Amount, reference: str = "") -> dict[str, Any]:
    """Move money in EUR between two accounts."""
    if amount > 5000:
        raise ToolError("Insufficient funds")
    return {"confirmation_id": "TX-1", "from_account": from_account, "to_account": to_account, "amount": amount}


def freeze_card(card_id: str, reason: str) -> dict[str, Any]:
    """Freeze a card."""
    return {"card_id": card_id, "status": "FROZEN"}


def get_exchange_rate(base: str, quote: str, amount: Amount) -> dict[str, Any]:
    """Exchange rate between two currencies, and an amount converted."""
    return {"base": base, "quote": quote, "rate": 1.08, "converted": round(amount * 1.08, 2)}


def simulate_loan(amount: float, years: int, annual_rate_percent: float = 4.2) -> dict[str, Any]:
    """Monthly payment of a loan."""
    return {"monthly_payment": 100.0}


def find_branches(city: str) -> dict[str, Any]:
    """Branches of a city."""
    return {"branches": [{"city": city}]}


TOOLS = [list_accounts, get_balance, list_transactions, transfer_funds, freeze_card, get_exchange_rate, simulate_loan,
         find_branches]


def bank_server(hidden: tuple[str, ...] = ()) -> MCPServer:
    """A new server each time: the session manager of one can only run once. `hidden` plays what mcp-acl does."""
    server = MCPServer("ACME Bank MCP", version="1.0.0")
    for tool in TOOLS:
        if tool.__name__ not in hidden:
            server.tool()(tool)
    return server


async def read_body(receive: Callable) -> bytes:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            return body


class Gateway:
    """Stands where the MCP proxy stands.

    `tokens` are the bearers it accepts (any when None, none needed when `open`); `answers` maps a tool name or an MCP
    method to the (status, body, headers) it answers instead of the server, or to a function of the JSON-RPC request
    that returns it. `requests` is what came in.
    """

    def __init__(self, app: Callable, tokens: set[str] | None = None, open: bool = False,
                 answers: dict[str, Any] | None = None) -> None:
        self.app, self.tokens, self.open, self.answers = app, tokens, open, answers or {}
        self.requests: list[dict[str, Any]] = []

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = await read_body(receive)
        try:
            rpc = json.loads(body)
        except ValueError:
            rpc = {}
        method = rpc.get("method") if isinstance(rpc, dict) else None
        tool = rpc["params"].get("name") if method == "tools/call" else None
        received = dict(scope["headers"])
        authorization = received.get(b"authorization", b"").decode()
        transaction = received.get(b"x-gravitee-transaction-id", b"").decode()
        self.requests.append({"method": method, "tool": tool, "authorization": authorization, "transaction": transaction})
        count = len(self.requests)
        # the gateway keeps a transaction id it is given, and makes one up otherwise; a request id is always its own
        ids = {"X-Gravitee-Transaction-Id": transaction or f"tx-{count}", "X-Gravitee-Request-Id": f"req-{count}"}
        forced = self.answers.get(tool) or self.answers.get(method)
        if not self.accepts(authorization):
            response: Response = JSONResponse({"message": "Unauthorized", "http_status_code": 401}, 401, headers=ids)
        elif forced:
            status, content, headers = forced(rpc) if callable(forced) else forced
            response = Response(json.dumps(content) if isinstance(content, (dict, list)) else content, status,
                                {**ids, **headers}, media_type="application/json")
        else:
            return await self.pass_through(scope, receive, body, send, ids)
        await response(scope, receive, send)

    def accepts(self, authorization: str) -> bool:
        if self.open:
            return True
        token = authorization[len("Bearer "):] if authorization.startswith("Bearer ") else ""
        return token in self.tokens if self.tokens is not None else bool(token)

    async def pass_through(self, scope: dict, receive: Callable, body: bytes, send: Callable,
                           ids: dict[str, str]) -> None:
        replayed = False

        async def replay() -> dict[str, Any]:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def stamped(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = [*message.get("headers", []), *((k.lower().encode(), v.encode()) for k, v in ids.items())]
                message = {**message, "headers": headers}
            await send(message)

        # the gateway strips its context path before the server sees the request
        await self.app({**scope, "path": "/", "raw_path": b"/"}, replay, stamped)

    def tool_calls(self) -> list[str]:
        return [r["tool"] for r in self.requests if r["tool"]]


class Unreachable(httpx2.AsyncBaseTransport, httpx.AsyncBaseTransport):
    """A transport for a service that is down (httpx and httpx2 each want their own base class)."""

    async def handle_async_request(self, request: Any) -> Any:
        raise (httpx2.ConnectError if isinstance(request, httpx2.Request) else httpx.ConnectError)("connection refused")


# ---- access management ------------------------------------------------------------------------------------------------

class StubAm:
    """The token endpoint of the `acme-bank` domain: client credentials for Ace, and the RFC 8693 exchange."""

    def __init__(self, lifetime: int = 7200) -> None:
        self.lifetime = lifetime
        self.requests: list[dict[str, str]] = []              # each form, with its Authorization header
        self.failure: Response | None = None
        self.exchange_claims: dict[str, Any] = {}             # what an exchange says instead; None leaves one out
        self.issued = 0
        self.forgotten: set[str] = set()                      # the jti of the actor tokens AM refuses

    async def token(self, request: Request) -> Response:
        form = dict(parse_qsl((await request.body()).decode()))
        form["authorization"] = request.headers.get("authorization", "")
        self.requests.append(form)
        if self.failure:
            return self.failure
        expected = "Basic " + base64.b64encode(f"ace-agent:{AGENT_SECRET}".encode()).decode()
        if form["authorization"] != expected:
            return JSONResponse({"error": "invalid_client", "error_description": "Bad client credentials"}, 401)
        self.issued += 1
        claims: dict[str, Any] = {"client_id": "ace-agent", "jti": f"jti-{self.issued}"}
        if form["grant_type"] == "client_credentials":
            claims["sub"] = "ace-agent"
        elif form["grant_type"] == TOKEN_EXCHANGE:
            if claims_of(form["actor_token"]).get("jti") in self.forgotten:
                return JSONResponse({"error": "invalid_request", "error_description": "The presented token is invalid"}, 400)
            claims.update({k: v for k, v in claims_of(form["subject_token"]).items() if k not in ("exp", "iat")})
            claims["act"] = {"sub": "ace-agent", "sub_profile": "hosted_delegated"}
            claims.update(self.exchange_claims)
        claims = {k: v for k, v in claims.items() if v is not None}
        return JSONResponse({"access_token": fake_jwt(**claims), "token_type": "bearer", "expires_in": self.lifetime,
                             "issued_token_type": ACCESS_TOKEN})

    def app(self) -> Starlette:
        return Starlette(routes=[Route("/acme-bank/oauth/token", self.token, methods=["POST"])])

    def grants(self) -> list[str]:
        return [r["grant_type"].split(":")[-1] for r in self.requests]     # client_credentials, token-exchange


# ---- everything wired -------------------------------------------------------------------------------------------------

BEHIND_THE_GATEWAY = Settings(
    llm_url="http://gateway/acme-bank/llm", llm_model="acme-chat", llm_api_key="ace-llm-key",
    llm_reasoning_effort="none",
    mcp_url="http://gateway/acme-bank/mcp", delegation=True, am_token_url="http://am/acme-bank/oauth/token",
    agent_client_id="ace-agent", agent_client_secret=AGENT_SECRET, public_url="http://bank-agent:8000", port=8000,
    allowed_hosts=("bank-agent",))
DIRECT = replace(BEHIND_THE_GATEWAY, llm_url="http://ollama/v1", llm_model="qwen3:1.7b", llm_api_key="",
                 mcp_url="http://bank-mcp:8000/", delegation=False, am_token_url="", agent_client_id="",
                 agent_client_secret="")


class World:
    """An Ace, its model, its AM and the bank behind a gateway, each a fake."""

    def __init__(self, settings: Settings = BEHIND_THE_GATEWAY, script: tuple[Any, ...] | list[Any] = ()) -> None:
        self.settings = settings
        self.llm = StubOpenAI(*script)
        self.am = StubAm()
        self.gateway: Gateway

    @contextlib.asynccontextmanager
    async def ace(self, hidden: tuple[str, ...] = (), llm_transport: Any = None, am_transport: Any = None,
                  mcp_transport: Any = None, **gateway: Any) -> AsyncIterator[Ace]:
        bank = bank_server(hidden).streamable_http_app(streamable_http_path="/", stateless_http=True,
                                                       json_response=True, host="0.0.0.0")
        # The lifespan starts and stops inside the test: anyio wants one task for both. A hanging test fails after 20 s.
        async with asyncio.timeout(20), bank.router.lifespan_context(bank):
            self.gateway = Gateway(bank, **gateway)
            llm_http = httpx2.AsyncClient(transport=llm_transport or httpx2.ASGITransport(app=self.llm.app()))
            am_http = httpx.AsyncClient(transport=am_transport or httpx.ASGITransport(app=self.am.app()))
            delegation = Delegation(self.settings, am_http) if self.settings.delegation else None
            ace = Ace(self.settings, Llm(self.settings, llm_http), delegation,
                      mcp_transport or httpx2.ASGITransport(app=self.gateway))
            try:
                yield ace
            finally:
                await ace.aclose()
