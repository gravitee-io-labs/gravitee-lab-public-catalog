"""What the generator waits for: real requests to the fake platform, which can be made not ready in four ways."""
import unittest
from unittest import mock

import readiness
from readiness import A2A, LLM, MCP, WORKSPACE, Readiness
from tests import fakes
from tests.fakes import generator
from wire import PlatformError


class Prerequisites(unittest.IsolatedAsyncioTestCase):
    async def waiting(self, runner):
        await runner.readiness.check()
        return runner.readiness.waiting

    async def test_a_platform_that_is_ready_waits_for_nothing(self):
        async with generator() as (platform, runner, clock):
            self.assertEqual(await self.waiting(runner), {})
            self.assertEqual(runner.readiness.ready, {LLM, MCP, A2A, WORKSPACE})

    async def test_the_llm_proxy_has_to_answer_with_the_traffic_key(self):
        async with generator(TRAFFIC_LLM_API_KEY="another-key") as (platform, runner, clock):
            waiting = await self.waiting(runner)
            self.assertEqual(list(waiting), [LLM])
            self.assertIn("the LLM proxy answered HTTP 401 to the Traffic key", waiting[LLM])

    async def test_alice_sees_seven_tools_while_tools_by_role_is_on_and_eight_while_it_is_off(self):
        async with generator() as (platform, runner, clock):
            self.assertEqual(await self.waiting(runner), {})
        with mock.patch.dict(fakes.USERS["alice"], {"role": "teller"}):         # a teller's tools: 8, as a customer's when the filter is off
            async with generator() as (platform, runner, clock):
                self.assertEqual(await self.waiting(runner), {})

    async def test_any_other_number_of_tools_is_a_platform_that_is_not_ready(self):
        with mock.patch.dict(fakes.USERS["alice"], {"role": "teller"}), mock.patch.object(readiness, "ALL_TOOL_COUNT", 9):
            async with generator() as (platform, runner, clock):
                waiting = await self.waiting(runner)
                self.assertEqual(waiting, {MCP: "the MCP proxy lists 8 tools to alice, expected 7 or 9"})

    async def test_a_public_tool_has_to_be_permitted_so_the_policies_are_loaded(self):
        with mock.patch.object(fakes, "permitted", lambda *args, **kwargs: False):
            async with generator() as (platform, runner, clock):
                waiting = await self.waiting(runner)
                self.assertIn("a public tool was not permitted to alice: denied", waiting[MCP])

    async def test_the_a2a_proxy_has_to_serve_the_card_to_alice(self):
        async with generator(BANK_DEMO_PASSWORD="wrong") as (platform, runner, clock):
            waiting = await self.waiting(runner)
            self.assertEqual(set(waiting), {MCP, A2A})                      # nobody can sign in
            self.assertIn("AM refused to sign alice in", waiting[A2A])

    async def test_the_workspace_has_to_exist(self):
        async with generator() as (platform, runner, clock):
            platform.workspace_exists = False
            waiting = await self.waiting(runner)
            self.assertEqual(waiting, {WORKSPACE: "the AI workspace ACME Bank Teams does not exist yet"})

    async def test_the_workspace_has_to_be_deployed(self):
        async with generator() as (platform, runner, clock):
            platform.workspace_state = "NEED_REDEPLOY"
            self.assertIn("is NEED_REDEPLOY, not DEPLOYED", (await self.waiting(runner))[WORKSPACE])

    async def test_the_key_of_a_team_has_to_be_accepted(self):
        async with generator() as (platform, runner, clock):
            platform.stale_keys["team-fraud"] = "stale"
            self.assertIn("HTTP 401 to team-fraud's key", (await self.waiting(runner))[WORKSPACE])

    async def test_a_gateway_that_is_restarting_is_waited_for(self):
        async with generator() as (platform, runner, clock):
            platform.down = True
            waiting = await self.waiting(runner)
            self.assertEqual(set(waiting), {LLM, MCP, A2A, WORKSPACE})


class Asking(unittest.IsolatedAsyncioTestCase):
    async def test_only_what_is_not_ready_is_asked_again(self):
        async with generator() as (platform, runner, clock):
            platform.workspace_exists = False
            await runner.readiness.check()
            asked = len(platform.calls)
            platform.workspace_exists = True
            await runner.readiness.check()
            workspace_side = ("/gamma", "/management", "/acme-bank-teams")
            elsewhere = [c["path"] for c in platform.calls[asked:] if not c["path"].startswith(workspace_side)]
            self.assertEqual(elsewhere, [])                       # only the workspace was asked again
            self.assertEqual(runner.readiness.waiting, {})

    async def test_a_feature_a_scenario_found_down_is_asked_again(self):
        async with generator() as (platform, runner, clock):
            await runner.readiness.check()
            runner.readiness.mark_down(WORKSPACE, "it stopped answering")
            self.assertEqual(runner.readiness.waiting, {WORKSPACE: "it stopped answering"})
            await runner.readiness.check()
            self.assertEqual(runner.readiness.waiting, {})

    async def test_a_probe_that_breaks_is_a_reason_not_a_crash(self):
        async def broken():
            raise ZeroDivisionError("oops")

        async def fails():
            raise PlatformError("the thing says no")
        readiness = Readiness({"a": broken, "b": fails})
        await readiness.check()
        self.assertEqual(readiness.waiting, {"a": "ZeroDivisionError: oops", "b": "the thing says no"})


if __name__ == "__main__":
    unittest.main()
