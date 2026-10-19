"""The control port, and the generator as a whole, against the fake platform."""
import asyncio
import contextlib
import unittest

import httpx

from checks import FAILED, SKIPPED
from control import RESTART_AFTER, build_app, keep_running
from runner import Pace
from scenarios import table
from tests.fakes import generator


@contextlib.asynccontextmanager
async def serving(runner, closed=None):
    """The control port of `runner`, with its lifespan: the loop runs while it is open."""
    async def close():
        closed.append(1) if closed is not None else None
    app = build_app(runner, close)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://traffic") as client:
            yield client


async def until(condition, turns=20000):
    for _ in range(turns):
        if condition():
            return
        await asyncio.sleep(0)
    raise AssertionError("it did not happen")


QUICK = Pace(warmup_calls=len(table()) + 3, warmup_seconds=0, interval=0, jitter=0, first_wait=1, longest_wait=1)


class Endpoints(unittest.IsolatedAsyncioTestCase):
    async def test_health_answers_while_the_platform_is_not_ready(self):
        async with generator() as (platform, runner, clock):
            platform.down = True
            async with serving(runner) as client:
                self.assertEqual((await client.get("/health")).json(), {"status": "ok"})
                await until(lambda: clock.slept)
                status = (await client.get("/status")).json()
                self.assertEqual(status["state"], "waiting")
                self.assertEqual(set(status["waiting_for"]), {"llm", "mcp", "a2a", "workspace"})

    async def test_status_says_what_is_going_on(self):
        async with generator(pace=QUICK) as (platform, runner, clock):
            async with serving(runner) as client:
                await until(lambda: runner.phase == "running")
                await until(lambda: runner.counters.totals()["runs"] > len(table()) + 3)
                status = (await client.get("/status")).json()
                self.assertEqual((status["state"], status["paused"], status["rate"]), ("running", False, 1.0))
                self.assertEqual(status["warmup"], {"done": len(table()) + 3, "of": len(table()) + 3})
                self.assertEqual(status["waiting_for"], {})
                self.assertEqual(set(status["scenarios"]), {s.name for s in table()})
                self.assertEqual(set(status["ledger"]["ace"]),
                                 {"unit", "limit", "window_seconds", "used", "cap", "percent"})
                self.assertEqual(status["transfers"]["owed"], [])

    async def test_pause_resume_and_reset(self):
        async with generator(pace=QUICK) as (platform, runner, clock):
            async with serving(runner) as client:
                await until(lambda: runner.phase == "running")
                self.assertEqual((await client.post("/pause")).json()["state"], "paused")
                await until(lambda: runner.current is None)
                runs = runner.counters.totals()["runs"]
                for _ in range(300):
                    await asyncio.sleep(0)
                self.assertEqual(runner.counters.totals()["runs"], runs)
                reset = (await client.post("/reset")).json()
                self.assertEqual(reset["totals"]["runs"], 0)
                self.assertEqual((await client.post("/resume")).json()["paused"], False)
                await until(lambda: runner.counters.totals()["runs"] > 0)

    async def test_traffic_off_starts_paused(self):
        async with generator(TRAFFIC="off", pace=QUICK) as (platform, runner, clock):
            async with serving(runner) as client:
                for _ in range(300):
                    await asyncio.sleep(0)
                status = (await client.get("/status")).json()
                self.assertEqual((status["state"], status["totals"]["runs"], platform.calls), ("paused", 0, []))
                await client.post("/resume")
                await until(lambda: runner.counters.totals()["runs"] > 0)

    async def test_the_actions_are_posts_and_nothing_else_is_there(self):
        async with generator() as (platform, runner, clock):
            async with serving(runner) as client:
                self.assertEqual((await client.get("/pause")).status_code, 405)
                self.assertEqual((await client.post("/status")).status_code, 405)
                self.assertEqual((await client.get("/admin")).status_code, 404)

    async def test_stopping_the_container_stops_the_loop_and_closes_the_clients(self):
        closed = []
        async with generator() as (platform, runner, clock):
            platform.down = True
            async with serving(runner, closed):
                await until(lambda: clock.slept)
            self.assertEqual(closed, [1])


class KeepRunning(unittest.IsolatedAsyncioTestCase):
    async def test_a_loop_that_stops_by_accident_is_started_again(self):
        class Runner:
            runs = 0

            async def run(self):
                self.runs += 1
                if self.runs == 1:
                    raise RuntimeError("an accident")
                await asyncio.sleep(3600)
        slept, runner = [], Runner()

        async def sleep(seconds):
            slept.append(seconds)
        with self.assertLogs("bank-traffic", "ERROR") as logs:
            task = asyncio.create_task(keep_running(runner, sleep))
            await until(lambda: runner.runs == 2)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.assertEqual(slept, [RESTART_AFTER])
        self.assertIn("the loop stopped, starting it again in 30 s", logs.output[0])


class WholeGenerator(unittest.IsolatedAsyncioTestCase):
    async def test_a_warm_up_and_a_trickle_against_a_platform_that_behaves(self):
        async with generator(pace=QUICK) as (platform, runner, clock):
            async with serving(runner) as client:
                await until(lambda: runner.counters.totals()["runs"] >= 2 * len(table()))
                await client.post("/pause")
                await until(lambda: runner.current is None)
                status = (await client.get("/status")).json()
        totals = status["totals"]
        self.assertEqual((totals[FAILED], totals[SKIPPED]), (0, 0), status["scenarios"])
        self.assertEqual(totals["inconclusive"], 0)
        self.assertEqual(platform.bank.balances["ACC-1001"], 4820.55)                  # every transfer came back
        self.assertEqual(status["transfers"]["moved_eur"], status["transfers"]["returned_eur"])
        self.assertGreater(status["transfers"]["moved_eur"], 0)
        self.assertEqual({call["agent"] for call in platform.calls}, {"acme-bank-traffic"})
        self.assertNotIn("hackathon", " ".join(f"{c['path']}?{c['query']} {c['headers'].get('authorization')}"
                                               for c in platform.calls))
        for name, used in status["ledger"].items():
            self.assertLessEqual(used["percent"], 40.0, name)                        # never above the share of a limit


if __name__ == "__main__":
    unittest.main()
