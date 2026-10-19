"""The control port: health, what the generator is doing, and the things the bank's page asks of it (pause, resume, start
over). It is internal to the playground's network and has no sign-in, like the bank's other apps behind the web app."""
import asyncio
import contextlib
import logging
from typing import Awaitable, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from runner import Runner

log = logging.getLogger("bank-traffic")
RESTART_AFTER = 30      # seconds


async def keep_running(runner: Runner, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
    """The loop does not raise, but if it ever does the traffic must not stop for good with /health still saying ok."""
    while True:
        try:
            await runner.run()
        except Exception:
            log.exception("the loop stopped, starting it again in %d s", RESTART_AFTER)
            await sleep(RESTART_AFTER)


def build_app(runner: Runner, close: Callable[[], Awaitable[None]]) -> Starlette:
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})          # alive, whatever the platform does: it is waited for in the loop

    async def status(request: Request) -> JSONResponse:
        return JSONResponse(runner.status())

    def action(name: str, act: Callable[[], None]):
        async def handle(request: Request) -> JSONResponse:
            act()
            log.info("%s asked from the control port", name)
            return JSONResponse(runner.status())
        return handle

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        task = asyncio.create_task(keep_running(runner))
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await close()

    return Starlette(lifespan=lifespan, routes=[
        Route("/health", health, methods=["GET"]),
        Route("/status", status, methods=["GET"]),
        Route("/pause", action("pause", runner.pause), methods=["POST"]),
        Route("/resume", action("resume", runner.resume), methods=["POST"]),
        Route("/reset", action("reset", runner.reset), methods=["POST"]),
    ])
