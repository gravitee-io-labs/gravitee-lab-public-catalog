"""Teams: the AI workspace called with the key of a team, read from the Gamma API and never sent to the page."""

from tests.base import AppCase
from tests.fakes import TEAM_USERS, TOKEN

CARE_KEY_PATH = "/gamma/organizations/DEFAULT/environments/DEFAULT/modules/aim/ai-workspaces/ws-1/users/s-u-2/api-key"


class Teams(AppCase):
    async def chat(self, team: str = "team-hackathon", kind: str = "long") -> dict:
        response = await self.http.post("/api/teams/chat", json={"team": team, "kind": kind})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_the_teams_and_where_their_spend_is(self):
        out = (await self.http.get("/api/teams")).json()
        self.assertEqual([t["id"] for t in out["teams"]], ["team-hackathon", "team-care", "team-fraud"])
        self.assertEqual(out["spend"], "http://gamma.test/environments/default/aim/ai-workspaces/ws-1/spend")

    async def test_the_key_of_the_team_is_read_from_the_gamma_api_and_sent_to_the_workspace_only(self):
        response = await self.http.post("/api/teams/chat", json={"team": "team-care", "kind": "short"})
        self.assertEqual(self.world.workspace.log[0]["key"], "key-team-care-1")
        self.assertNotIn("key-team", response.text)
        self.assertNotIn("key-team", (await self.http.get("/api/teams")).text)
        self.assertTrue(any(path.endswith("/users/s-u-2/api-key") for path in self.world.apim.log))

    async def test_a_short_and_a_long_answer_ask_for_different_lengths_and_never_a_thinking_budget(self):
        await self.chat(kind="short")
        await self.chat(kind="long")
        short, long = (entry["body"] for entry in self.world.workspace.log)
        self.assertLess(short["max_tokens"], long["max_tokens"])
        self.assertEqual((short["reasoning_effort"], long["reasoning_effort"]), ("none", "none"))

    async def test_the_budget_is_shown_with_the_model_that_answered(self):
        out = await self.chat()
        self.assertEqual((out["status"], out["model"], out["answer"]), (200, "smart", "A team answer."))
        self.assertEqual(out["budget"], {"limit": 0.12, "left": 0.11, "percent_left": 92})   # the gateway holds 10,000 for a first call
        self.assertEqual(out["tokens"]["total"], 430)

    async def test_the_hackathon_budget_goes_from_smart_to_lite_and_then_stops(self):
        answers = [await self.chat()]
        while answers[-1]["status"] == 200 and len(answers) < 30:
            answers.append(await self.chat())
        models = [a["model"] for a in answers if a["status"] == 200]
        # The router decides on what the gateway has counted when it lets a call in (the spend plus what it expects the call to
        # cost): 8%, 36%, then 54% of the budget, where it moves the team to lite
        self.assertEqual(models, ["smart"] * 2 + ["lite"] * 7)
        self.assertEqual([a["budget"]["percent_left"] for a in answers[:3]], [92, 64, 46])
        last = answers[-1]
        self.assertEqual(last["status"], 429)
        self.assertIn("Cost budget exceeded", last["message"])
        self.assertEqual(last["budget"], {"limit": 0.12, "left": 0.0, "percent_left": 0})
        self.assertEqual((last["request_id"], last["transaction_id"]), (f"req-ws-{len(answers)}", f"tx-ws-{len(answers)}"), "even a refusal has the ids of its evidence")

    async def test_another_team_has_its_own_budget(self):
        for _ in range(12):
            await self.chat("team-hackathon")
        out = await self.chat("team-care")
        self.assertEqual((out["status"], out["model"], out["budget"]["limit"]), (200, "smart", 5.0))

    async def test_a_key_that_was_replaced_is_read_again_after_a_401(self):
        await self.chat("team-care")
        reads = self.world.apim.log.count(CARE_KEY_PATH)
        self.world.workspace.keys["team-care"] = "key-team-care-2"  # a re-seed made a new one
        out = await self.chat("team-care")
        self.assertEqual(out["status"], 200)
        self.assertEqual(
            [entry["key"] for entry in self.world.workspace.log],
            ["key-team-care-1", "key-team-care-1", "key-team-care-2"],
        )
        self.assertEqual(self.world.apim.log.count(CARE_KEY_PATH), reads + 1)

    async def test_the_keys_are_read_once_not_at_every_question(self):
        await self.chat()
        await self.chat()
        self.assertEqual(sum(path.endswith("/api-key") for path in self.world.apim.log), len(TEAM_USERS))

    async def test_an_unknown_team_or_answer_is_refused(self):
        for body in ({"team": "team-x", "kind": "long"}, {"team": "team-care", "kind": "huge"}, {}):
            self.assertEqual((await self.http.post("/api/teams/chat", json=body)).status_code, 400, body)
        self.assertEqual(self.world.workspace.log, [])

    async def test_a_log_line_names_the_team_not_the_key(self):
        with self.assertLogs("bank-web", level="INFO") as logs:
            await self.chat("team-care")
        self.assertIn("team-care", "\n".join(logs.output))
        self.assertNotIn("key-team", "\n".join(logs.output))


class WhenTheWorkspaceIsNotThere(AppCase):
    async def test_the_page_is_told_to_re_seed(self):
        self.world.apim.workspace_exists = False
        response = await self.http.post("/api/teams/chat", json={"team": "team-care", "kind": "short"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["error"], "The AI workspace ACME Bank Teams does not exist. Re-seed the playground."
        )
        self.assertIsNone((await self.http.get("/api/teams")).json()["spend"])


class WithTheSeedsCredentials(AppCase):
    async def test_the_management_api_gets_the_user_and_password(self):
        await self.http.post("/api/teams/chat", json={"team": "team-care", "kind": "short"})
        self.assertEqual({a[:6] for a in self.world.apim.auth}, {"Basic "})


class WithWrongCredentials(AppCase):
    settings_overrides = {"apim_password": "wrong"}

    async def test_the_page_says_the_management_api_refused_them(self):
        response = await self.http.post("/api/teams/chat", json={"team": "team-care", "kind": "short"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("refused the credentials (HTTP 401)", response.json()["error"])


class WithAToken(AppCase):
    settings_overrides = {"apim_token": TOKEN, "apim_username": "", "apim_password": ""}

    async def test_a_bearer_token_is_sent_in_place_of_the_password(self):
        await self.http.post("/api/teams/chat", json={"team": "team-care", "kind": "short"})
        self.assertEqual(set(self.world.apim.auth), {f"Bearer {TOKEN}"})
