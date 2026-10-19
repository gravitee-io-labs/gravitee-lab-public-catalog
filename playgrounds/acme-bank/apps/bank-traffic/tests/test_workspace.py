"""The keys of the AI workspace's users, read from the Gamma API: at start, and again after a 401."""
import unittest

from clients import Teams
from tests.fakes import Platform, settings
from wire import PlatformError
from workspace import Workspace


class Keys(unittest.IsolatedAsyncioTestCase):
    async def test_the_keys_and_the_entrypoint_come_from_gamma(self):
        async with Platform() as platform:
            workspace = Workspace(settings(), platform.transports()[0])
            await workspace.load(deployed=True)
            self.assertEqual((workspace.key("team-care"), workspace.key("team-fraud"), workspace.entrypoint),
                             ("key-care", "key-fraud", "http://gateway/acme-bank-teams"))
            await workspace.aclose()

    async def test_team_hackathon_is_never_asked_for(self):
        async with Platform() as platform:
            workspace = Workspace(settings(), platform.transports()[0])
            await workspace.load()
            asked = " ".join(call["path"] + "?" + call["query"] for call in platform.calls)
            self.assertNotIn("hackathon", asked)
            with self.assertRaises(KeyError):
                workspace.key("team-hackathon")
            await workspace.aclose()

    async def test_the_management_api_is_called_with_the_login_of_the_seed(self):
        async with Platform() as platform:
            workspace = Workspace(settings(), platform.transports()[0])
            await workspace.load()
            self.assertTrue(all(call["headers"]["authorization"].startswith("Basic ") for call in platform.calls))
            self.assertEqual({call["agent"] for call in platform.calls}, {"acme-bank-traffic"})
            await workspace.aclose()

    async def test_a_token_is_sent_as_a_bearer(self):
        async with Platform() as platform:
            env = {"APIM_USERNAME": "", "APIM_PASSWORD": "", "APIM_TOKEN": "api-token"}
            workspace = Workspace(settings(**env), platform.transports()[0])
            with self.assertRaises(PlatformError):                    # the fake platform only knows the login
                await workspace.load()
            self.assertEqual(platform.calls[0]["headers"]["authorization"], "Bearer api-token")
            await workspace.aclose()

    async def test_a_workspace_that_does_not_exist_yet_is_said(self):
        async with Platform() as platform:
            platform.workspace_exists = False
            workspace = Workspace(settings(), platform.transports()[0])
            with self.assertRaisesRegex(PlatformError, "ACME Bank Teams does not exist yet"):
                await workspace.load()
            self.assertFalse(workspace.loaded)
            await workspace.aclose()

    async def test_a_first_start_waits_for_the_deployment_but_a_new_key_does_not(self):
        async with Platform() as platform:
            platform.workspace_state = "NEED_REDEPLOY"
            workspace = Workspace(settings(), platform.transports()[0])
            with self.assertRaisesRegex(PlatformError, "NEED_REDEPLOY, not DEPLOYED"):
                await workspace.load(deployed=True)
            await workspace.load()
            self.assertTrue(workspace.loaded)
            await workspace.aclose()

    async def test_a_management_api_that_is_still_starting_is_a_reason_to_wait(self):
        async with Platform() as platform:
            workspace = Workspace(settings(APIM_PASSWORD="wrong"), platform.transports()[0])
            with self.assertRaisesRegex(PlatformError, "HTTP 401"):
                await workspace.load()
            await workspace.aclose()


class AfterA401(unittest.IsolatedAsyncioTestCase):
    async def test_a_key_that_changed_is_read_again_and_the_call_made_once_more(self):
        async with Platform() as platform:
            httpx_transport, httpx2_transport = platform.transports()
            teams = Teams(Workspace(settings(), httpx_transport), httpx2_transport)
            first = await teams.chat("team-care", "hello", max_tokens=20)
            self.assertEqual(first.status, 200)
            self.assertEqual(platform.bodies[0][1]["model"], "smart")             # an alias of the workspace
            platform.team_keys["team-care"] = "key-care-rotated"          # the user is removed and added again
            reads = len(platform.seen("/gamma"))
            second = await teams.chat("team-care", "hello", max_tokens=20)
            self.assertEqual(second.status, 200)
            self.assertGreater(len(platform.seen("/gamma")), reads)         # the keys were read from Gamma again
            sent = [c["headers"]["authorization"] for c in platform.seen("/acme-bank-teams")]
            self.assertEqual(sent, ["Bearer key-care", "Bearer key-care", "Bearer key-care-rotated"])   # one refused, one retry
            await teams.aclose()

    async def test_a_key_that_is_refused_twice_comes_back_as_a_401(self):
        async with Platform() as platform:
            httpx_transport, httpx2_transport = platform.transports()
            teams = Teams(Workspace(settings(), httpx_transport), httpx2_transport)
            platform.stale_keys["team-care"] = "not-what-the-gateway-accepts"
            reply = await teams.chat("team-care", "hello", max_tokens=20)
            self.assertEqual(reply.status, 401)
            self.assertEqual(len(platform.seen("/acme-bank-teams")), 2)        # no third attempt
            await teams.aclose()


if __name__ == "__main__":
    unittest.main()
