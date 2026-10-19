"""Ace over A2A 1.0: the agent card, JSON-RPC at the root and /health, on Starlette and uvicorn.

    python server.py          # configured by environment variables, see README.md

The executor reads the caller's token from the request headers the SDK puts in `call_context.state["headers"]`
(lower-case names). Behind the gateway that is the user's access token: the A2A proxy checked it at AM and forwards it.
It answers only to the names in ALLOWED_HOSTS and only to a JSON body (security.py says why).
"""
import contextlib
import logging
from typing import Any, AsyncIterator

import uvicorn
from a2a.helpers import new_data_part, new_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from chat import Ace
from gateway import incoming_transaction
from security import Guard
from settings import ConfigError, Settings

GRACEFUL_SHUTDOWN = 5          # seconds a chat in progress gets when the container is stopped
# Where clients written for earlier A2A versions, and the platform's card probe, look for the card. The A2A proxy
# turns a 404 there into a 500 with a stack trace in the gateway's log, so the same card is served here too
LEGACY_CARD_PATH = "/.well-known/agent.json"
SKILLS = [
    AgentSkill(id="accounts", name="Accounts", description="Balances, accounts and transactions of a customer.",
               tags=["bank", "accounts"], examples=["Show my accounts and balances",
                                                    "Show my last 5 transactions on ACC-1001"]),
    AgentSkill(id="payments", name="Payments", description="Moves money between accounts, within the bank's limits.",
               tags=["bank", "payments"], examples=["Send 120 EUR from ACC-1001 to ACC-2001"]),
    AgentSkill(id="cards", name="Cards", description="Freezes a card (bank staff).",
               tags=["bank", "cards"], examples=["Freeze CARD-1001, it was stolen"]),
    AgentSkill(id="rates", name="Rates and loans", description="Exchange rates, loan simulations and branches.",
               tags=["bank", "rates"], examples=["Convert 100 EUR to USD"]),
]


def bearer_of(authorization: str) -> str | None:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def request_headers(context: RequestContext) -> dict[str, Any]:
    return context.call_context.state.get("headers", {}) if context.call_context else {}


class AceExecutor(AgentExecutor):
    def __init__(self, ace: Ace) -> None:
        self.ace = ace

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        headers = request_headers(context)
        bearer = bearer_of(headers.get("authorization", ""))
        reply = await self.ace.reply(context.get_user_input(), bearer, incoming_transaction(headers))
        # One message with a text part and a data part, and no task id: a task id that a client sends back in its next
        # turn fails with "task not found", since no task is ever stored. The context id carries the conversation.
        await event_queue.enqueue_event(new_message([new_text_part(reply.answer), new_data_part(reply.data)],
                                                    context_id=context.context_id))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("a chat turn cannot be cancelled")


def build_card(public_url: str) -> AgentCard:
    return AgentCard(
        name="Ace",
        description="ACME Bank's assistant: accounts, payments, exchange rates and loans, "
                    "within the rights of the user it acts for.",
        version="1.0.0",
        supported_interfaces=[AgentInterface(url=public_url, protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "application/json"],
        skills=SKILLS,
    )


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def build_app(settings: Settings, ace: Ace | None = None) -> Starlette:
    ace = ace or Ace.from_settings(settings)
    card = build_card(settings.public_url)
    handler = DefaultRequestHandler(agent_executor=AceExecutor(ace), task_store=InMemoryTaskStore(), agent_card=card)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        yield
        await ace.aclose()

    return Starlette(routes=[Route("/health", health, methods=["GET"]), *create_agent_card_routes(card),
                             *create_agent_card_routes(card, card_url=LEGACY_CARD_PATH),
                             *create_jsonrpc_routes(handler, rpc_url="/")],
                     middleware=[Middleware(Guard, allowed_hosts=settings.allowed_hosts)], lifespan=lifespan)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for noisy in ("httpx", "httpx2", "httpcore", "httpcore2"):      # one line per request each: Ace logs one per step
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
    except ConfigError as e:
        raise SystemExit(f"bank-agent: {e}") from e
    logging.getLogger("bank-agent").info("Ace talks to %s and to %s, delegation %s", settings.llm_url, settings.mcp_url,
                                         "on" if settings.delegation else "off")
    uvicorn.run(build_app(settings), host="0.0.0.0", port=settings.port, log_level="info",
                timeout_graceful_shutdown=GRACEFUL_SHUTDOWN)


if __name__ == "__main__":
    main()
