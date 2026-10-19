"""ACME Bank MCP server: the bank's tools, prompts and resources over Streamable HTTP.

It has no authentication on purpose: a gateway in front of it decides who may call what, and the playground
publishes its port to show what happens without one. The one exception is POST /admin/reset, which needs the token
in ADMIN_TOKEN. It does check the name it is reached by, so that a web page cannot use the published port through a
name of its own that points at this machine. Configuration: HTTP_PORT (default 8000), ALLOWED_HOSTS (the names it is
reached by, localhost by default) and ADMIN_TOKEN (no default: without it the reset is off).

The tool descriptions are what a small local model reads to pick a tool and fill its arguments, and the tests pin their
text: after any change, chat the guide's example questions with Ace and the guard rails on, then take the new digests.
"""
import hmac
import logging
import os
import time
from datetime import date
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

import policies
import public_data
from data import Bank

log = logging.getLogger("bank-mcp")

# the transaction dates count back from the day the container starts
BANK = Bank(date.today())

DEFAULT_HOSTS = ("localhost", "127.0.0.1", "[::1]")


def http_options(allowed_hosts: str = "") -> dict[str, Any]:
    """How the server is served. A page on a hostile name that points at this machine (the DNS rebinding trick) sends
    that name in its Host header, and a browser sends an Origin with a call it makes: the SDK refuses both unless they
    are listed here, with any port. Listening on every interface lets the gateway and the other containers in, and the
    SDK only checks the Host when told to: on 127.0.0.1 it would do it by itself, for the loopback names alone.
    The root path makes the gateway's target the bare origin. Stateless and plain JSON: no session to lose on a
    restart."""
    names = [name.strip().lower() for name in allowed_hosts.split(",") if name.strip()] or list(DEFAULT_HOSTS)
    hosts = [pattern for name in names for pattern in (name, f"{name}:*")]
    origins = [f"{scheme}://{pattern}" for scheme in ("http", "https") for pattern in hosts]
    return {"host": "0.0.0.0", "streamable_http_path": "/", "stateless_http": True, "json_response": True,
            "transport_security": TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)}


READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
MOVES_MONEY = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)
FREEZES = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)

# strict: only a JSON number. The SDK reads arguments leniently, so the string "12000" would become 12000.0 here
# while a gateway rule that reads the raw request sees a string and may not apply its limit to it
Amount = Annotated[float, Field(strict=True, gt=0, description="Amount in EUR, a JSON number")]
# the same, for an amount that is converted: it is in the currency it is converted from
AmountToConvert = Annotated[float, Field(strict=True, gt=0,
                                         description="Sum to convert, in the base currency; 1 for the plain rate")]
BaseCurrency = Annotated[str, Field(description="Currency the amount is in (the one to convert from)")]
QuoteCurrency = Annotated[str, Field(description="Currency to convert the amount into")]


async def log_requests(ctx, call_next):
    """One INFO line per MCP request, naming the tool, prompt or resource: uvicorn only says `POST / 200`.
    Arguments are never logged."""
    if ctx.request_id is None:  # a notification, not a request
        return await call_next(ctx)
    params = ctx.params or {}
    started, outcome = time.monotonic(), "failed"
    try:
        result = await call_next(ctx)
        outcome = "tool error" if isinstance(result, dict) and result.get("isError") else "ok"
        return result
    finally:
        target = params.get("name") or params.get("uri")
        log.info("%s -> %s in %d ms (protocol %s)", f"{ctx.method} {target}" if target else ctx.method, outcome,
                 (time.monotonic() - started) * 1000, ctx.protocol_version)


mcp = MCPServer(
    "ACME Bank MCP",
    version="1.0.0",
    instructions=("ACME Bank core banking tools. Amounts are in EUR unless a currency is given. Customer ids start "
                  "with C-, account ids with ACC- and card ids with CARD-."),
    middleware=[log_requests],
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def admin_refusal(request: Request) -> str | None:
    """Why this request may not use the admin route, or None when it may. The gateway's MCP proxy answers 404 to every
    path but its root, so only a request that goes around the gateway, by the published port, gets here: the token is
    its lock. It is what only the bank's web app (bank-web) has; with none set, nobody has one."""
    expected = os.environ.get("ADMIN_TOKEN", "")
    if not expected:
        return "ADMIN_TOKEN is not set on this server"
    if not hmac.compare_digest(request.headers.get("X-Admin-Token", "").encode(), expected.encode()):
        return "the X-Admin-Token header is missing or wrong"
    return None


@mcp.custom_route("/admin/reset", methods=["POST"])
async def reset(request: Request) -> JSONResponse:
    """Back to the starting data between two demos: balances, cards and the transfer counter."""
    refusal = admin_refusal(request)
    if refusal:
        log.warning("admin/reset -> refused: %s", refusal)
        return JSONResponse({"error": "forbidden", "message": "The admin token is missing or wrong."}, status_code=403)
    BANK.reset()
    log.info("admin/reset -> balances, cards and the transfer counter are back to their start")
    return JSONResponse({"status": "reset"})


# The descriptions below are the tuned ones. An id written as an example (ACC-1001), and id arguments left without a
# description of their own in the schema, are part of it: take either out and a small local model asks the customer
# which account they meant instead of calling a tool.
@mcp.tool(annotations=READ_ONLY, description=(
    "List the accounts of a customer: account id, type (checking or savings), currency and balance. Use it for any "
    "balance question, and to find an account the user names by type (my savings, my checking account)."))
def list_accounts(customer_id: str) -> dict[str, Any]:
    return BANK.list_accounts(customer_id)


@mcp.tool(annotations=READ_ONLY, description="Get the current balance of one account, from its account id (ACC-1001).")
def get_balance(account_id: str) -> dict[str, Any]:
    return BANK.get_balance(account_id)


@mcp.tool(annotations=READ_ONLY, description=(
    "List the latest transactions of one account, newest first. Optional: limit (default 10) and category "
    "(groceries, rent, salary, transport, restaurants, subscriptions, utilities)."))
def list_transactions(account_id: str, limit: int = 10, category: str | None = None) -> dict[str, Any]:
    return BANK.list_transactions(account_id, limit, category)


@mcp.tool(annotations=MOVES_MONEY, description=(
    "Move money in EUR from one account (from_account, debited) to another (to_account, credited), both as account "
    "ids like ACC-1001. Call it only when the user gave the amount and both accounts; if they name accounts by type "
    "(savings, checking), call list_accounts first."))
def transfer_funds(from_account: str, to_account: str, amount: Amount, reference: str = "") -> dict[str, Any]:
    return BANK.transfer(from_account, to_account, amount, reference)


@mcp.tool(annotations=FREEZES, description=(
    "Freeze a payment card (bank staff only). Needs the card id (CARD-1001) and a short reason."))
def freeze_card(card_id: str, reason: str) -> dict[str, Any]:
    return BANK.freeze_card(card_id, reason)


@mcp.tool(annotations=READ_ONLY, description=(
    "Convert an amount from one currency to another, with the rate (3-letter codes: EUR, USD, GBP, CHF, JPY, CAD, "
    "SEK). amount is the sum the customer gives and base is the currency that sum is in: \"10000 JPY in euros\" is "
    "base JPY, quote EUR, amount 10000. Without a sum use amount 1 for the plain rate. The result already holds the "
    "converted amount."))
def get_exchange_rate(base: BaseCurrency, quote: QuoteCurrency, amount: AmountToConvert) -> dict[str, Any]:
    return public_data.exchange_rate(base, quote, amount)


@mcp.tool(annotations=READ_ONLY, description=(
    "Simulate a loan: monthly payment and total cost for an amount in EUR, a duration in years and an optional "
    "yearly interest rate in percent (default 4.2)."))
def simulate_loan(amount: Amount, years: int, annual_rate_percent: float = 4.2) -> dict[str, Any]:
    return public_data.simulate_loan(amount, years, annual_rate_percent)


@mcp.tool(annotations=READ_ONLY, description="Find the ACME Bank branches in a city, with address and opening hours.")
def find_branches(city: str) -> dict[str, Any]:
    return public_data.find_branches(city)


@mcp.prompt(description="Ask for a summary of the spending of one account over one month.")
def summarize_spending(
    account_id: Annotated[str, Field(description="Account id: ACC- followed by digits")],
    month: Annotated[str, Field(description="Month, such as 2026-09")],
) -> str:
    return (f"Summarize the spending of account {account_id} in {month}: the total by category, the biggest "
            "payments and anything unusual. Read the transactions with the bank's tools and do not guess a figure.")


@mcp.prompt(description="Start a dispute about one transaction.")
def dispute_charge(transaction_id: Annotated[str, Field(description="Transaction id: TX- followed by digits")]) -> str:
    return (f"Help the customer dispute transaction {transaction_id}: ask what is wrong with it, then explain the "
            "next steps in plain words.")


@mcp.resource("acme://policies/fees", name="fees", title="Fee schedule", mime_type="text/markdown",
              description="What ACME Bank charges for its services, and its transfer limits.")
def fees() -> str:
    return policies.FEES


@mcp.resource("acme://policies/card-security", name="card-security", title="Card security policy",
              mime_type="text/markdown", description="What to do with a lost or stolen card, and how to keep one safe.")
def card_security() -> str:
    return policies.CARD_SECURITY


if __name__ == "__main__":
    # MCPServer() has already set a bare log format; force=True swaps in one with the time and the logger name
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", force=True)
    # The SDK adds its own INFO lines: the text of a failed tool, which echoes the ids it was given, and "Terminating
    # session" after every call. The log_requests line says it all.
    for noisy in ("mcp.server.mcpserver.server", "mcp.server.streamable_http"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    mcp.run("streamable-http", port=int(os.environ.get("HTTP_PORT", "8000")),
            **http_options(os.environ.get("ALLOWED_HOSTS", "")))
