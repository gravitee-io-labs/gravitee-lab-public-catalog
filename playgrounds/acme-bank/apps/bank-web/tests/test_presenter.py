"""The Presenter view: the check, the warm-up, the reset and the traffic control. The check needs nobody (the two proxies that ask a user for a token are called with none,
and answer with the 401 of their plan). The warm-up of Ace calls the gateway as a user, with the token of the person who is signed in: the app holds no password and signs
nobody in by itself."""

from unittest import mock

from starlette.responses import JSONResponse

import presenter
from tests.base import AppCase
from tests.fakes import bearer_claims


class Never(set):
    """A semantic cache that keeps nothing."""

    def add(self, item):
        pass

    def __contains__(self, item):
        return False


class Check(AppCase):
    async def check(self) -> dict:
        response = await self.http.get("/api/presenter/check")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def statuses(self, out: dict) -> dict:
        return {item["id"]: item["status"] for item in out["items"]}

    async def test_a_platform_that_is_ready_is_green_everywhere(self):
        out = await self.check()
        self.assertTrue(out["ready"])
        self.assertEqual(set(self.statuses(out).values()), {"ok"})
        self.assertEqual(
            [item["id"] for item in out["items"]],
            ["am", "llm", "mcp", "a2a", "workspace", "ollama", "cache", "identity", "traffic", "dashboard"],
        )
        self.assertTrue(all(item["fix"] == "" for item in out["items"]))

    async def test_the_check_needs_nobody_the_two_proxies_are_called_with_no_token_and_nobody_is_signed_in(self):
        out = await self.check()
        self.assertTrue(out["ready"], "nobody is signed in and nothing is red because of it")
        self.assertEqual(self.world.am.log, [])
        listing = next(m for m in self.world.mcp.log if m["method"] == "tools/list")
        self.assertIsNone(listing["authorization"])
        both = {item["id"]: (item["label"], item["status"], item["detail"]) for item in out["items"] if item["id"] in ("mcp", "a2a")}
        self.assertEqual(both, {"mcp": ("The MCP proxy answers", "ok", "It asks for a token"), "a2a": ("The A2A proxy answers", "ok", "It asks for a token")})

    async def test_a_proxy_is_ready_when_it_refuses_a_call_with_no_token_and_not_when_it_lets_anybody_in_or_is_not_there(self):
        self.world.mcp.protected = False                                  # a plan that was taken off: the call is answered
        self.world.gateway_ace.answer_with = JSONResponse({"message": "Not found"}, status_code=404)       # a proxy that was never published
        out = await self.check()
        self.assertFalse(out["ready"])
        found = {item["id"]: item for item in out["items"]}
        self.assertEqual((found["mcp"]["status"], found["mcp"]["detail"]), ("fail", "HTTP 200, not the 401 of its plan"))
        self.assertEqual((found["a2a"]["status"], found["a2a"]["detail"]), ("fail", "HTTP 404, not the 401 of its plan"))
        for key in ("mcp", "a2a"):
            self.assertIn("Re-seed", found[key]["fix"])
            self.assertNotIn("Choose who", found[key]["detail"] + found[key]["fix"], "the check never asks for a person")

    async def test_what_is_not_ready_is_red_with_a_line_that_says_how_to_fix_it(self):
        self.world.am.down = True
        out = await self.check()
        self.assertFalse(out["ready"])
        statuses = self.statuses(out)
        self.assertEqual((statuses["am"], statuses["llm"], statuses["mcp"]), ("fail", "ok", "ok"))
        am = next(item for item in out["items"] if item["id"] == "am")
        self.assertEqual(am["detail"], "Access Management answered HTTP 503")
        self.assertIn("Re-seed", am["fix"])

    async def test_access_management_answers_when_its_discovery_names_a_login_page_and_a_token_endpoint(self):
        out = await self.check()
        am = next(item for item in out["items"] if item["id"] == "am")
        self.assertEqual((am["status"], am["detail"], am["label"]), ("ok", "", "Access Management answers"))
        self.assertEqual(self.world.am.log, [], "nothing of the check was a grant")
        self.world.am.discovery_document = {"issuer": "x"}                                           # an answer that is not Access Management's
        am = next(item for item in (await self.check())["items"] if item["id"] == "am")
        self.assertEqual((am["status"], am["detail"]), ("fail", "Its discovery document has no login page"))

    async def test_a_model_that_answers_slowly_is_only_a_warning(self):
        with mock.patch.object(presenter, "WARM_MS", 0):
            out = await self.check()
        self.assertEqual(self.statuses(out)["ollama"], "warn")
        self.assertTrue(out["ready"])
        self.assertIn("Warm up", next(i for i in out["items"] if i["id"] == "ollama")["fix"])

    async def test_a_developers_key_out_of_tokens_is_a_warning_not_a_broken_platform(self):
        self.world.llm.used = self.world.llm.limit
        out = await self.check()
        statuses = self.statuses(out)
        self.assertEqual((statuses["ollama"], statuses["cache"]), ("warn", "warn"))
        self.assertTrue(out["ready"])
        self.assertIn("wait a minute", next(i for i in out["items"] if i["id"] == "ollama")["detail"])

    async def test_the_check_says_nothing_of_the_protections_whatever_they_are(self):
        """Whether a protection is on is Gamma's to say: the Presenter's check neither reads nor judges it, and a platform whose protections are all
        off is as ready as one whose protections are all on."""
        for control in ("pii", "guard", "tools", "pep", "cap", "router"):
            setattr(self.world.controls, control, False)
        out = await self.check()
        self.assertTrue(out["ready"])
        self.assertEqual({item["group"] for item in out["items"]}, {"platform", "data"})
        self.assertEqual({item["status"] for item in out["items"]}, {"ok"})
        self.assertFalse(any("state" in item for item in out["items"]))
        self.assertFalse(any(path.endswith("/policies") or "/router" in path for path in self.world.apim.log), "no read of the configuration of a protection")

    async def test_the_other_checks_stay_strict_when_the_protections_are_off(self):
        for control in ("guard", "tools", "pep", "router"):
            setattr(self.world.controls, control, False)
        self.world.llm.cached = Never()
        self.world.apim.agents = []
        statuses = self.statuses(await self.check())
        self.assertEqual((statuses["cache"], statuses["identity"]), ("fail", "fail"))

    async def test_a_cache_that_never_answers_is_red(self):
        self.world.llm.cached = Never()
        out = await self.check()
        self.assertEqual(self.statuses(out)["cache"], "fail")
        self.assertEqual(self.statuses(out)["llm"], "ok")

    def identity(self, out: dict) -> dict:
        return next(item for item in out["items"] if item["id"] == "identity")

    async def test_ace_missing_from_agent_identity_is_red(self):
        self.world.apim.agents = []
        item = self.identity(await self.check())
        self.assertEqual((item["status"], item["detail"]), ("fail", "Ace is not in the list of the linked domain"))
        self.assertIn("Re-seed", item["fix"])

    async def test_agent_identity_is_read_in_the_domain_gamma_is_linked_to(self):
        self.world.apim.link.update(environmentId="env-7", defaultDomainId="dom-7")
        item = self.identity(await self.check())
        self.assertEqual((item["status"], item["detail"]), ("ok", "Ace"))
        agents = [path for path in self.world.apim.log if path.endswith("/agents")]
        self.assertEqual(len(agents), 1)
        self.assertTrue(agents[0].endswith("/aim/identity/environments/env-7/domains/dom-7/agents"))

    async def test_a_gamma_that_is_not_linked_to_access_management_is_red_and_no_agent_is_asked_for(self):
        unlinked = (
            {"baseUrl": "", "hasAccessToken": False},  # what Gamma answers before anything is saved
            {"baseUrl": "http://am", "hasAccessToken": False, "environmentId": "DEFAULT", "defaultDomainId": "dom-1"},
            {"baseUrl": "http://am", "hasAccessToken": True},
        )
        for link in unlinked:
            with self.subTest(link=link):
                self.world.apim.link = link
                item = self.identity(await self.check())
                self.assertEqual((item["status"], item["detail"]), ("fail", "Gamma is not linked to Access Management"))
                self.assertIn("Re-seed", item["fix"])
        self.assertFalse(any(path.endswith("/agents") for path in self.world.apim.log))

    async def test_a_link_whose_agents_gamma_cannot_list_is_red(self):
        self.world.apim.identity_status = 503
        item = self.identity(await self.check())
        self.assertEqual(item["status"], "fail")
        self.assertIn("HTTP 503", item["detail"])
        self.assertIn("Re-seed", item["fix"])

    async def test_the_workspace_that_is_not_deployed_is_red(self):
        self.world.apim.workspace_exists = False
        out = await self.check()
        self.assertEqual(self.statuses(out)["workspace"], "fail")
        self.assertIn("does not exist", next(i for i in out["items"] if i["id"] == "workspace")["detail"])

    async def test_the_traffic_paused_is_a_warning_and_a_dead_one_is_red(self):
        self.world.traffic.paused = True
        out = await self.check()
        self.assertEqual((self.statuses(out)["traffic"], out["ready"]), ("warn", True))
        self.world.transport.hosts.pop("traffic.test")
        self.assertEqual(self.statuses(await self.check())["traffic"], "fail")

    async def test_the_dashboard_without_data_is_a_warning_and_a_missing_one_is_red(self):
        self.world.apim.requests_last_hour = 0
        self.assertEqual(self.statuses(await self.check())["dashboard"], "warn")
        self.world.apim.dashboards = []
        self.assertEqual(self.statuses(await self.check())["dashboard"], "fail")

    async def test_a_check_that_breaks_does_not_hide_the_others(self):
        self.world.transport.hosts.pop("apim.test")
        statuses = self.statuses(await self.check())
        self.assertEqual((statuses["workspace"], statuses["identity"], statuses["dashboard"]), ("fail", "fail", "fail"))
        self.assertEqual((statuses["am"], statuses["llm"], statuses["mcp"]), ("ok", "ok", "ok"))


class WithAWrongDevelopersKey(AppCase):
    settings_overrides = {"dev_llm_api_key": "wrong"}

    async def test_the_checks_that_use_it_fail(self):
        items = (await self.http.get("/api/presenter/check")).json()["items"]
        statuses = {item["id"]: item["status"] for item in items}
        self.assertEqual((statuses["llm"], statuses["ollama"], statuses["am"]), ("fail", "fail", "ok"))


class WarmUp(AppCase):
    async def test_the_slow_first_calls_are_made_one_after_the_other(self):
        await self.sign_in("alice")
        out = (await self.http.post("/api/presenter/warmup")).json()
        self.assertEqual(
            [(s["label"], s["status"]) for s in out["steps"]],
            [("Model smart", "ok"), ("Model lite", "ok"), ("Guard rails model", "ok"), ("Ace", "ok")],
        )
        self.assertEqual([e["body"]["model"] for e in self.world.llm.log[:2]], ["acme-chat", "acme-lite"])
        self.assertEqual(self.world.ace.log[0]["text"], "Show my accounts and balances")
        self.assertEqual(out["steps"][3]["detail"], "Your balance is EUR 4,820.55.")

    async def test_a_step_that_fails_does_not_stop_the_others(self):
        await self.sign_in("alice")
        self.world.gateway_ace.refuse_with = 504
        out = (await self.http.post("/api/presenter/warmup")).json()
        self.assertEqual([s["status"] for s in out["steps"]], ["ok", "ok", "ok", "fail"])
        self.assertEqual(out["steps"][3]["detail"], "Ace is not answering. Try again in a minute.")

    async def test_ace_is_asked_with_the_token_of_the_person_signed_in_and_in_a_conversation_that_is_not_theirs(self):
        await self.sign_in("tina")
        session = next(iter(self.web.sessions._items.values()))
        await self.http.post("/api/presenter/warmup")
        self.assertEqual(bearer_claims(self.world.ace.log[0]["authorization"])["username"], "tina@acme-bank.test")
        self.assertEqual(session.contexts, {}, "the warm-up is nobody's conversation")

    async def test_ace_is_not_warmed_by_nobody_the_step_says_to_choose_who_is_asking_and_the_others_go_on(self):
        out = (await self.http.post("/api/presenter/warmup")).json()
        self.assertEqual([s["status"] for s in out["steps"]], ["ok", "ok", "ok", "fail"])
        self.assertEqual(out["steps"][3]["detail"], "Choose who is asking first: Ace answers with their token")
        self.assertEqual(self.world.ace.log, [])


class Reset(AppCase):
    async def test_the_bank_the_traffic_counters_and_the_conversations_start_again(self):
        await self.sign_in("alice")
        await self.chat("one")
        out = (await self.http.post("/api/presenter/reset")).json()
        self.assertEqual(
            out, {"bank": {"ok": True, "detail": "HTTP 200"}, "traffic": {"ok": True, "detail": "HTTP 200"}}
        )
        self.assertEqual((self.world.bank.resets, self.world.traffic.resets), (1, 1))
        self.assertEqual(next(iter(self.web.sessions._items.values())).contexts, {})

    async def test_the_bank_refuses_a_reset_that_does_not_carry_its_admin_token(self):
        self.web.presenter.settings = self.world.settings(admin_token="")
        out = (await self.http.post("/api/presenter/reset")).json()
        self.assertEqual(out["bank"], {"ok": False, "detail": "HTTP 403"})
        self.assertEqual(self.world.bank.resets, 0)

    async def test_a_part_that_does_not_answer_is_said_and_the_rest_is_done(self):
        self.world.transport.hosts.pop("traffic.test")
        out = (await self.http.post("/api/presenter/reset")).json()
        self.assertEqual((out["bank"]["ok"], out["traffic"]["ok"]), (True, False))
        self.assertEqual(self.world.bank.resets, 1)


class Traffic(AppCase):
    async def test_the_traffic_can_be_paused_and_resumed(self):
        status = (await self.http.get("/api/presenter/traffic")).json()
        self.assertEqual((status["paused"], status["status"]["calls"]), (False, 12))
        self.assertTrue((await self.http.post("/api/presenter/traffic", json={"action": "pause"})).json()["paused"])
        self.assertTrue(self.world.traffic.paused)
        self.assertFalse((await self.http.post("/api/presenter/traffic", json={"action": "resume"})).json()["paused"])

    async def test_the_status_lists_what_the_generator_reports_without_its_nested_parts(self):
        status = (await self.http.get("/api/presenter/traffic")).json()["status"]
        self.assertEqual(status, {"paused": False, "calls": 12, "errors": 0})

    async def test_any_other_action_is_refused(self):
        for body in ({}, {"action": "reset"}, {"action": "kill"}):
            self.assertEqual((await self.http.post("/api/presenter/traffic", json=body)).status_code, 400, body)
        self.assertFalse(self.world.traffic.paused)

    async def test_a_generator_that_does_not_answer_is_said(self):
        self.world.transport.hosts.pop("traffic.test")
        response = await self.http.get("/api/presenter/traffic")
        self.assertEqual((response.status_code, response.json()["error"]), (502, "Traffic control is not answering"))
