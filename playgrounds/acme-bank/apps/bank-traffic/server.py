"""bank-traffic: a gentle trickle of realistic calls through the gateway, so the dashboards and the logs of the
demo are never empty. Run it with `python server.py`; the settings are environment variables (README.md)."""
import logging
import random
import sys
from typing import Awaitable, Callable

import httpx
import httpx2
import uvicorn

from clients import Ace, Llm, Teams, Tools
from control import build_app
from ledger import Ledger
from readiness import Readiness, probes
from runner import Pace, Runner
from scenarios import World, table
from settings import ConfigError, Settings
from tokens import Tokens
from transfers import Transfers
from workspace import Workspace


def assemble(settings: Settings, httpx_transport: httpx.AsyncBaseTransport | None = None,
             httpx2_transport: httpx2.AsyncBaseTransport | None = None, pace: Pace = Pace(),
             rng: random.Random | None = None, **timing) -> tuple[Runner, Callable[[], Awaitable[None]]]:
    """The generator wired to a platform. The transports are for the tests, which reach a fake platform in memory;
    `timing` is the clock and the sleep of the runner, for the same reason."""
    tokens = Tokens(settings, httpx_transport)
    ace = Ace(settings, tokens, httpx_transport)
    tools = Tools(settings, tokens, httpx2_transport)
    llm = Llm(settings.llm_url, settings.llm_api_key, httpx2_transport)
    teams = Teams(Workspace(settings, httpx_transport), httpx2_transport)
    world = World(ace, tools, llm, teams, Ledger(), Transfers(tools), rng or random.Random())
    readiness = Readiness(probes(llm, tools, ace, teams, settings.protections))
    runner = Runner(world, table(settings.protections), readiness, settings.rate, settings.enabled, pace, **timing)

    async def close() -> None:
        for client in (ace, llm, teams, tokens):
            await client.aclose()
    return runner, close


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigError as e:
        sys.exit(f"bank-traffic: {e}")
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        datefmt="%H:%M:%S")
    log = logging.getLogger("bank-traffic")
    log.setLevel(logging.INFO)
    runner, close = assemble(settings)
    protections = ("on: a denial or a block is expected" if settings.protections
                   else "off: a call that goes through is accepted")
    log.info("starting: rate %g, %s, protections %s, control port %d", settings.rate,
             "on" if settings.enabled else "paused until /resume", protections, settings.port)
    uvicorn.run(build_app(runner, close), host="0.0.0.0", port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
