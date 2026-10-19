"""The app over the fakes of tests/fakes.py, on a real port: for looking at the page and for tests/smoke.py.

python -m tests.fake_stack [port] [off=guard,tools,pep,cap,router] [slow=seconds] [fail=ace] [down=apim]

`off` starts those protections switched off, as the lab does: the fake gateway then lets through what it would have stopped (leave `off` out for all on).
`slow` makes Ace take that long to answer, to see the page wait. `fail=ace` has the gateway answer 504 to every question for Ace; `down=apim` has the
management API not answer, so that the evidence of a call cannot be looked up.
Access Management's login page is the fake's too, on the next port (`port + 1`): it signs the person in at once, so that a sign-in opens the window, sends the
browser back and closes it, as it does at the real one. In a container, HOST=0.0.0.0 lets the published ports reach them.
"""

import asyncio
import os
import sys
import threading
import time

import uvicorn

from server import build_app
from tests.fakes import World


def main() -> None:
    world = World()
    port, options = 8110, {}
    for arg in sys.argv[1:]:
        key, _, value = arg.partition("=")
        if value:
            options[key] = value
        else:
            port = int(arg)
    world.apim.clock = time.time                 # a served page lives in real time
    for control in filter(None, options.get("off", "").split(",")):
        setattr(world.controls, control, False)
    if options.get("fail") == "ace":
        world.gateway_ace.refuse_with = 504
    if options.get("down") == "apim":
        world.transport.hosts.pop("apim.test")
    if options.get("slow"):
        delay, execute = float(options["slow"]), world.ace.execute

        async def slowly(context, event_queue):
            await asyncio.sleep(delay)
            await execute(context, event_queue)

        world.ace.execute = slowly
    host = os.environ.get("HOST", "127.0.0.1")
    login = uvicorn.Server(uvicorn.Config(world.am.app(), host=host, port=port + 1, log_level="warning"))
    threading.Thread(target=login.run, daemon=True).start()
    settings = world.settings(am_authorize_url=f"http://localhost:{port + 1}/acme-bank/oauth/authorize")
    uvicorn.run(build_app(settings, world.clients()), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
