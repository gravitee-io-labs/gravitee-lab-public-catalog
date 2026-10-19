"""ACME Bank open API: the bank's branches and exchange rates, read only and without authentication.

It is a plain REST API on purpose: the playground puts it behind a gateway, then turns its OpenAPI document into tools
for AI agents. The document is written by hand in openapi.json and served at /openapi.json.
Configuration: HTTP_PORT (default 8000). Uvicorn's access log is the log: one line per request.
"""
import json
import os
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import public_data

OPENAPI = json.loads((Path(__file__).parent / "openapi.json").read_text())


def error(status, code, message, headers=None):
    return JSONResponse({"error": code, "message": message}, status_code=status, headers=headers)


def supported():
    return ", ".join(public_data.EUR_RATES)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def openapi(request: Request) -> JSONResponse:
    return JSONResponse(OPENAPI)


async def list_branches(request: Request) -> JSONResponse:
    city = request.query_params.get("city", "").strip().lower()
    branches = [branch for branch in public_data.BRANCHES if not city or branch["city"].lower() == city]
    return JSONResponse({"count": len(branches), "branches": branches})


async def get_branch(request: Request) -> JSONResponse:
    branch_id = request.path_params["id"]
    for branch in public_data.BRANCHES:
        if branch["id"] == branch_id:
            return JSONResponse(branch)
    return error(404, "not_found", f"No branch has the id {branch_id}.")


async def list_rates(request: Request) -> JSONResponse:
    base = request.query_params.get("base", "EUR").strip().upper()
    if base not in public_data.EUR_RATES:
        return error(400, "unsupported_currency", f"Unsupported currency {base}. Supported: {supported()}.")
    rates = {quote: public_data.rate(base, quote) for quote in public_data.EUR_RATES if quote != base}
    return JSONResponse({"base": base, "date": public_data.RATE_DATE, "rates": rates})


async def get_rate(request: Request) -> JSONResponse:
    base, quote = (request.path_params[name].strip().upper() for name in ("base", "quote"))
    for code in (base, quote):
        if code not in public_data.EUR_RATES:
            return error(404, "unsupported_currency", f"Unsupported currency {code}. Supported: {supported()}.")
    return JSONResponse({"base": base, "quote": quote, "rate": public_data.rate(base, quote),
                         "date": public_data.RATE_DATE})


async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    """A route that does not exist or a method that is not allowed answers in the same shape as the other errors."""
    return error(exc.status_code, "not_found" if exc.status_code == 404 else "error", exc.detail, exc.headers)


# No Host check, unlike bank-agent and bank-mcp: the data is public and read only, so a web page that reaches it by
# another name learns nothing it could not read anyway
app = Starlette(
    routes=[
        Route("/health", health),
        Route("/openapi.json", openapi),
        Route("/branches", list_branches),
        Route("/branches/{id}", get_branch),
        Route("/rates", list_rates),
        Route("/rates/{base}/{quote}", get_rate),
    ],
    exception_handlers={HTTPException: http_error},
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("HTTP_PORT", "8000")))
