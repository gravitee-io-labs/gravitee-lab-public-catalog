"""The small pieces on their own: links, hops, claims, settings, and the calls that need no app around them."""

import asyncio
import base64
import json
import unittest

import httpx

import apis
import llm
import mcp_rpc
from claims import jwt_claims
from links import Links
from management import Management
from settings import ConfigError, Settings
from upstream import Clients, UpstreamError, recording
from tests.fakes import fake_jwt


def query_of(url: str) -> dict:
    """The `q` of a link of the console, decoded: base64url of JSON, without padding."""
    raw = url.split("q=")[1].split("&")[0]
    assert "=" not in raw, "base64url without padding"
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


class Link(unittest.TestCase):
    links = Links("http://localhost:8086/", "DEFAULT")
    BASE = "http://localhost:8086/environments/default"

    def test_the_log_entry_of_a_request_is_a_page_of_its_own_and_needs_the_api_that_served_it(self):
        self.assertEqual(self.links.log("api-1234", "req-5678"), f"{self.BASE}/aim/observe/logs/req-5678?apiId=api-1234")

    def test_a_decision_is_the_page_of_its_event_in_the_decisions_of_the_console(self):
        self.assertEqual(self.links.decision("api-1234", "evt-9999"), f"{self.BASE}/authz/observe/logs/evt-9999?apiId=api-1234")

    def test_an_id_stays_in_its_segment_whatever_the_platform_called_it(self):
        url = self.links.log("a/../b?x=1", "r#/../../etc")
        self.assertEqual(url, f"{self.BASE}/aim/observe/logs/r%23%2F..%2F..%2Fetc?apiId=a%2F..%2Fb%3Fx%3D1")

    def test_a_list_is_filtered_on_the_request_over_an_absolute_window_that_does_not_empty(self):
        for url, page in ((self.links.logs_list("req-5678", (1000, 2000)), "aim/observe/logs"),
                          (self.links.decisions_list("req-5678", (1000, 2000)), "authz/observe/logs")):
            self.assertTrue(url.startswith(f"{self.BASE}/{page}?q="), url)
            self.assertTrue(url.endswith("&v=1"))
            self.assertEqual(query_of(url), {"c": [{"field": "REQUEST_ID", "label": "Request ID", "operator": "eq", "value": ["req-5678"]}],
                                             "t": {"type": "absolute", "from": 1000, "to": 2000}})

    def test_the_dashboard_of_a_workspace_is_filtered_on_the_person_and_the_window_of_the_run(self):
        url = self.links.spend_dashboard("ws-1", "app-1", (1000, 2000))
        self.assertTrue(url.startswith(f"{self.BASE}/aim/observe/dashboards/ai-workspace-overview?q="), url)
        self.assertEqual(query_of(url), {"c": [{"field": "API_PRODUCT", "label": "AI Workspace", "operator": "eq", "value": ["ws-1"]},
                                               {"field": "APPLICATION", "label": "User", "operator": "eq", "value": ["app-1"]}],
                                         "t": {"type": "absolute", "from": 1000, "to": 2000}})
        self.assertEqual([c["field"] for c in query_of(self.links.spend_dashboard("ws-1", None, (1, 2)))["c"]], ["API_PRODUCT"], "no person: the workspace")

    def test_the_workspace_pages(self):
        self.assertEqual(self.links.spend("ws-1"), f"{self.BASE}/aim/ai-workspaces/ws-1/spend")
        self.assertIsNone(self.links.spend(None))
        self.assertEqual(self.links.workspaces(), f"{self.BASE}/aim/ai-workspaces")


class Trace(unittest.TestCase):
    def test_the_link_opens_an_apis_tracing_page_or_one_of_its_traces(self):
        links = Links("http://localhost:8086/", "DEFAULT")
        base = "http://localhost:8086/environments/default/aim/observe/tracing/api-1"
        self.assertEqual(links.trace("api-1"), base)
        self.assertEqual(links.trace("api-1", "c9467422f631b6941b77f1bbb4ab4a0f"), f"{base}/c9467422f631b6941b77f1bbb4ab4a0f")
        self.assertIsNone(links.trace(None, "c9467422f631b6941b77f1bbb4ab4a0f"))

    def test_the_traces_of_an_api_can_be_those_of_a_window(self):
        url = Links("http://g", "DEFAULT").trace("api-1", window=(1000, 2000))
        self.assertTrue(url.startswith("http://g/environments/default/aim/observe/tracing/api-1?q="))
        self.assertEqual(query_of(url), {"c": [], "t": {"type": "absolute", "from": 1000, "to": 2000}})

    def test_the_consoles_evidence_pages(self):
        self.assertEqual(Links("http://g/", "DEFAULT").pages(), {
            "dashboards": "http://g/environments/default/aim/observe/dashboards",
            "logs": "http://g/environments/default/aim/observe/logs",
            "tracing": "http://g/environments/default/aim/observe/tracing",
            "decisions": "http://g/environments/default/authz/observe/logs"})


class Apis(unittest.IsolatedAsyncioTestCase):
    def apis(self, handler, clock=lambda: 1000.0) -> apis.Apis:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(http.aclose)
        return apis.Apis(Management(http, Settings(web_client_secret="s", demo_password="p", apim_token="t")), clock)

    async def test_the_seeds_two_ids_are_known_without_asking(self):
        found = self.apis(lambda r: httpx.Response(500))
        self.assertEqual(await found.id("llm"), "00000000-0000-4000-8000-acb100000001")
        self.assertEqual(await found.id("a2a"), "00000000-0000-4000-8000-acb200000001")

    async def test_the_others_are_read_by_name_once(self):
        asked = []

        def handler(request):
            asked.append(request.url.params["q"])
            return httpx.Response(200, json={"data": [{"id": "x", "name": "ACME Bank MCP Studio"}, {"id": "mcp-1", "name": "ACME Bank MCP"}]})

        found = self.apis(handler)
        self.assertEqual((await found.id("mcp"), await found.id("mcp")), ("mcp-1", "mcp-1"))
        self.assertEqual(asked, ["ACME Bank MCP"])

    async def test_an_api_that_is_not_there_yet_is_looked_for_again_after_a_while(self):
        now, asked = [1000.0], []

        def handler(request):
            asked.append(1)
            return httpx.Response(200, json={"data": []})

        found = self.apis(handler, lambda: now[0])
        self.assertIsNone(await found.id("teams"))
        self.assertIsNone(await found.id("teams"))
        self.assertEqual(len(asked), 1)
        now[0] += apis.RETRY_AFTER + 1
        self.assertIsNone(await found.id("teams"))
        self.assertEqual(len(asked), 2)

    async def test_a_management_api_that_does_not_answer_is_no_id_and_no_error(self):
        found = self.apis(lambda r: httpx.Response(503, json={"message": "down"}))
        self.assertIsNone(await found.id("mcp"))
        self.assertIsNone(await found.id("nothing"))


class Claims(unittest.TestCase):
    def test_the_claims_of_a_token_are_read_without_checking_it(self):
        self.assertEqual(jwt_claims(fake_jwt({"sub": "a", "accounts": ["ACC-1"]})), {"sub": "a", "accounts": ["ACC-1"]})

    def test_what_is_not_a_token_has_no_claims(self):
        for junk in ("", "abc", "a.b.c", "a.bm90IGpzb24.c", "a." + base64.urlsafe_b64encode(b"[1]").decode() + ".c"):
            self.assertEqual(jwt_claims(junk), {}, junk)


class Configuration(unittest.TestCase):
    SECRETS = {"WEB_CLIENT_SECRET": "s", "BANK_DEMO_PASSWORD": "p"}

    def test_the_two_secrets_are_required(self):
        with self.assertRaisesRegex(ConfigError, "not set: WEB_CLIENT_SECRET, BANK_DEMO_PASSWORD"):
            Settings.from_env({})
        with self.assertRaisesRegex(ConfigError, "not set: BANK_DEMO_PASSWORD"):
            Settings.from_env({"WEB_CLIENT_SECRET": "s", "BANK_DEMO_PASSWORD": "  "})

    def test_everything_else_has_the_labs_address_and_can_be_set(self):
        settings = Settings.from_env(
            {
                **self.SECRETS,
                "ACE_URL": "http://x/ace/",
                "HTTP_PORT": "9000",
                "ALLOWED_HOSTS": " a.test , B.test ",
                "TRAFFIC_URL": " ",
            }
        )
        self.assertEqual(
            (settings.ace_url, settings.http_port, settings.allowed_hosts),
            ("http://x/ace/", 9000, ("a.test", "b.test")),
        )
        self.assertEqual(settings.traffic_url, "http://bank-traffic:8000")  # an empty variable is not set
        self.assertEqual(settings.web_client_id, "acme-bank-web")
        defaults = Settings.from_env(self.SECRETS)
        self.assertEqual((defaults.allowed_hosts, defaults.http_port), (("localhost", "127.0.0.1", "[::1]"), 8000))

    def test_a_port_that_is_not_a_number_is_one_line_not_a_traceback(self):
        for port in ("http", "80.80", "-1", "\u00b2"):
            with self.assertRaisesRegex(ConfigError, "HTTP_PORT is .*: use a port number"):
                Settings.from_env({**self.SECRETS, "HTTP_PORT": port})


class Mcp(unittest.IsolatedAsyncioTestCase):
    async def test_an_answer_as_an_event_stream_is_read(self):
        def handler(request):
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "a"}, {"name": "b"}]}})
            return httpx.Response(
                200, text=f"event: message\ndata: {body}\n\n", headers={"content-type": "text/event-stream"}
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            self.assertEqual(await mcp_rpc.list_tools(http, "http://x/"), ["a", "b"])

    async def test_a_server_that_does_not_list_its_tools_is_an_error(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "Unauthorized"}))
        ) as http:
            with self.assertRaises(UpstreamError) as raised:
                await mcp_rpc.list_tools(http, "http://x/")
        self.assertIn("HTTP 401", raised.exception.message)


class Completion(unittest.IsolatedAsyncioTestCase):
    async def complete(self, handler) -> dict:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await llm.complete(http, "http://x/llm/", {}, {}, "x-token-rate-limit")

    async def test_tokens_come_from_the_gateways_headers_when_the_body_has_no_usage(self):
        out = await self.complete(
            lambda r: httpx.Response(
                200,
                json={"choices": [{"message": {"content": "hi"}}]},
                headers={"x-llm-proxy-tokens-sent": "40", "x-llm-proxy-tokens-received": "9"},
            )
        )
        self.assertEqual(out["tokens"], {"prompt": 40, "completion": 9, "total": 49})

    async def test_an_empty_gateway_timeout_is_still_a_message(self):
        out = await self.complete(lambda r: httpx.Response(504))
        self.assertEqual((out["status"], out["message"], out["answer"]), (504, "HTTP 504", ""))

    async def test_an_answer_with_no_text_is_empty_not_an_error(self):
        out = await self.complete(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": None}}]}))
        self.assertEqual((out["status"], out["answer"], out["tokens"]), (200, "", None))


class Recording(unittest.IsolatedAsyncioTestCase):
    async def test_two_calls_at_once_each_keep_their_own_answer(self):
        async def handler(request):
            await asyncio.sleep(0.01 if request.url.path == "/slow" else 0)
            return httpx.Response(
                200 if request.url.path == "/slow" else 401, headers={"x-gravitee-transaction-id": request.url.path}
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients = Clients(am=client, a2a=client, gateway=client, gamma=client, internal=client)

        async def call(path):
            with recording() as seen:
                await clients.a2a.get(f"http://x{path}")
                await asyncio.sleep(0.02)
                return seen

        slow, fast = await asyncio.gather(call("/slow"), call("/fast"))
        self.assertEqual((slow["status"], slow["transaction_id"]), (200, "/slow"))
        self.assertEqual((fast["status"], fast["transaction_id"]), (401, "/fast"))
        await clients.aclose()


if __name__ == "__main__":
    unittest.main()


class WhatThePlatformSays(unittest.IsolatedAsyncioTestCase):
    """A platform's own words are for the log: the page gets a sentence, and what is logged is cut."""

    async def test_an_error_of_the_platform_keeps_its_words_in_the_detail_cut_to_200_characters_and_not_in_the_message(self):
        import httpx

        def answer(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "x" * 500 + " http://internal-apim:8083"})

        client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
        self.addAsyncCleanup(client.aclose)
        management = Management(client, Settings(web_client_secret="s", demo_password="p", apim_management_url="http://apim.test", apim_username="a",
                                                 apim_password="b"))
        with self.assertRaises(UpstreamError) as raised:
            await management.get("http://apim.test/x")
        error = raised.exception
        self.assertEqual((error.message, error.upstream, error.status), ("The management API answered HTTP 500", 500, 502))
        self.assertEqual(len(error.detail), 200)
        self.assertNotIn("internal-apim", error.message)


class QuietLibraries(unittest.TestCase):
    def test_the_http_client_logs_a_warning_and_not_a_line_for_every_call_to_the_platform(self):
        """The app reads the platform for the evidence: an INFO line per call buried the lines that matter."""
        import logging

        import server

        httpx_log = logging.getLogger("httpx")
        before = httpx_log.level
        self.addCleanup(httpx_log.setLevel, before)
        httpx_log.setLevel(logging.NOTSET)
        server.quiet_libraries()
        self.assertEqual(httpx_log.level, logging.WARNING)
        self.assertFalse(httpx_log.isEnabledFor(logging.INFO))
        import inspect
        self.assertIn("quiet_libraries()", inspect.getsource(server.main), "main applies it")
