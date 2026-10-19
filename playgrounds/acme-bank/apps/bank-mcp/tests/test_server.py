"""The server as a client sees it: the official SDK client, in process or through the real ASGI app (no socket)."""
import contextlib
import hashlib
import json
import logging
import os
import re
import unittest
from unittest import mock

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

import policies
import server as srv

# The SDK and the server log every request at INFO, and the server warns about a refused reset; the tests that care read
# them with assertLogs, the rest stays quiet
logging.getLogger().setLevel(logging.WARNING)
logging.getLogger("bank-mcp").setLevel(logging.ERROR)
logging.getLogger("asyncio").setLevel(logging.ERROR)  # the debug mode of the test loop reports a first slow call
logging.getLogger("mcp.server.transport_security").setLevel(logging.ERROR)  # one warning per refused name or origin

TOOLS = ["list_accounts", "get_balance", "list_transactions", "transfer_funds", "freeze_card", "get_exchange_rate",
         "simulate_loan", "find_branches"]
# What a model reads of each tool, its description and the schema of its arguments, is pinned by a digest: an id given
# as a format instead of an example, or each id described in the schema, makes a small local model ask the customer
# which account they meant instead of calling a tool. A digest that no longer matches means the text changed: chat the
# guide's example questions with Ace and the guard rails on, then take the new digest.
TUNED = {
    "list_accounts": "fe7a42b0619d",
    "get_balance": "cfd418dce02f",
    "list_transactions": "f278e9ea69e3",
    "transfer_funds": "481a07780d07",
    "freeze_card": "3655c651cd6d",
    "get_exchange_rate": "b8340835a510",
    "simulate_loan": "46e3b9d4ded7",
    "find_branches": "90b413ed333c",
}
ERAS = {"legacy": "2025-11-25", "2026-07-28": "2026-07-28", "auto": "2026-07-28"}
URL = "http://bank-mcp:8000/"
MOVE = {"from_account": "ACC-9001", "to_account": "ACC-1001"}
TOKEN = "demo-admin-token"


@contextlib.contextmanager
def admin_token(value):
    """ADMIN_TOKEN as the container would have it: set to value, or not set at all when value is None."""
    with mock.patch.dict(os.environ):
        os.environ.pop("ADMIN_TOKEN", None)
        if value is not None:
            os.environ["ADMIN_TOKEN"] = value
        yield


@contextlib.asynccontextmanager
async def served(hosts="bank-mcp"):
    """The real app behind an in-memory transport, reached by the name the other containers use (ALLOWED_HOSTS). httpx
    does not run the ASGI lifespan, so it is started here, inside the test: anyio scopes must not cross asyncSetUp."""
    app = srv.mcp.streamable_http_app(**srv.http_options(hosts))
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url=URL) as http:
            yield http


class Case(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        srv.BANK.reset()

    def data(self, result):
        self.assertFalse(result.is_error, result.content[0].text if result.content else "")
        return result.structured_content

    def error(self, result):
        self.assertTrue(result.is_error, result.structured_content)
        return result.content[0].text


class Catalog(Case):
    async def test_the_server_is_named_so_that_its_catalog_slug_is_acme_bank_mcp(self):
        async with Client(srv.mcp, mode="legacy") as c:
            name, version, instructions = c.server_info.name, c.server_info.version, c.instructions
        self.assertEqual((name, version), ("ACME Bank MCP", "1.0.0"))
        self.assertIn("EUR", instructions)
        self.assertEqual(re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), "acme-bank-mcp")

    async def test_eight_tools_each_with_annotations(self):
        async with Client(srv.mcp) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
        self.assertEqual(list(tools), TOOLS)
        for name, tool in tools.items():
            with self.subTest(tool=name):
                writes = name in ("transfer_funds", "freeze_card")
                self.assertFalse(tool.annotations.open_world_hint)
                self.assertEqual(tool.annotations.read_only_hint, not writes)
                self.assertEqual(tool.annotations.destructive_hint, writes)

    async def test_what_the_model_reads_of_each_tool_is_the_tuned_text(self):
        async with Client(srv.mcp) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
        for name, expected in TUNED.items():
            with self.subTest(tool=name):
                seen = {"description": tools[name].description, "parameters": tools[name].input_schema}
                digest = hashlib.sha256(json.dumps(seen, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                self.assertEqual(digest[:12], expected, json.dumps(seen, indent=1))

    async def test_ids_are_given_as_examples_in_the_descriptions_and_bare_in_the_schema(self):
        async with Client(srv.mcp) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
        described = {name: tool.description for name, tool in tools.items()}
        self.assertIn("(ACC-1001)", described["get_balance"])
        self.assertIn("like ACC-1001", described["transfer_funds"])
        self.assertIn("(CARD-1001)", described["freeze_card"])
        self.assertIn("call list_accounts first", described["transfer_funds"])
        self.assertIn("my savings", described["list_accounts"])
        self.assertIn('"10000 JPY in euros" is base JPY, quote EUR', described["get_exchange_rate"])
        self.assertIn("amount 1 for the plain rate", described["get_exchange_rate"])
        self.assertIn("The result already holds the converted amount", described["get_exchange_rate"])
        self.assertIn("(default 4.2)", described["simulate_loan"])
        for name, argument in [("list_accounts", "customer_id"), ("get_balance", "account_id"),
                               ("list_transactions", "account_id"), ("transfer_funds", "from_account"),
                               ("freeze_card", "card_id")]:
            with self.subTest(tool=name):
                self.assertEqual(tools[name].input_schema["properties"][argument],
                                 {"title": argument.replace("_", " ").title(), "type": "string"})

    async def test_only_what_the_model_must_give_is_required(self):
        async with Client(srv.mcp) as c:
            schemas = {t.name: t.input_schema for t in (await c.list_tools()).tools}
        self.assertEqual(schemas["list_transactions"]["required"], ["account_id"])
        self.assertEqual(schemas["transfer_funds"]["required"], ["from_account", "to_account", "amount"])
        self.assertEqual(schemas["simulate_loan"]["required"], ["amount", "years"])
        self.assertEqual(schemas["simulate_loan"]["properties"]["annual_rate_percent"]["default"], 4.2)
        self.assertEqual(schemas["get_exchange_rate"]["required"], ["base", "quote", "amount"])

    async def test_two_prompts(self):
        async with Client(srv.mcp) as c:
            prompts = {p.name: p for p in (await c.list_prompts()).prompts}
            spending = await c.get_prompt("summarize_spending", {"account_id": "ACC-1001", "month": "2026-09"})
            dispute = await c.get_prompt("dispute_charge", {"transaction_id": "TX-1001-03"})
        self.assertEqual(sorted(prompts), ["dispute_charge", "summarize_spending"])
        self.assertEqual([a.name for a in prompts["summarize_spending"].arguments], ["account_id", "month"])
        self.assertEqual([a.name for a in prompts["dispute_charge"].arguments], ["transaction_id"])
        self.assertIn("account ACC-1001 in 2026-09", spending.messages[0].content.text)
        self.assertIn("transaction TX-1001-03", dispute.messages[0].content.text)

    async def test_two_policy_resources_in_markdown(self):
        async with Client(srv.mcp) as c:
            listed = {r.uri: r for r in (await c.list_resources()).resources}
            fees = (await c.read_resource("acme://policies/fees")).contents[0]
            card = (await c.read_resource("acme://policies/card-security")).contents[0]
        self.assertEqual(sorted(listed), ["acme://policies/card-security", "acme://policies/fees"])
        self.assertEqual({r.mime_type for r in listed.values()}, {"text/markdown"})
        self.assertEqual((fees.text, card.text), (policies.FEES, policies.CARD_SECURITY))
        self.assertIn("EUR 10,000", fees.text)
        self.assertIn("EUR 500", fees.text)
        self.assertIn("lost or stolen", card.text)


class Tools(Case):
    async def ok(self, name, **arguments):
        async with Client(srv.mcp) as c:
            return self.data(await c.call_tool(name, arguments))

    async def fails(self, name, **arguments):
        async with Client(srv.mcp) as c:
            return self.error(await c.call_tool(name, arguments))

    async def test_list_accounts(self):
        result = await self.ok("list_accounts", customer_id="C-1001")
        self.assertEqual([a["account_id"] for a in result["accounts"]], ["ACC-1001", "ACC-1002"])
        self.assertIn("Unknown customer C-5", await self.fails("list_accounts", customer_id="C-5"))

    async def test_get_balance(self):
        self.assertEqual(await self.ok("get_balance", account_id="ACC-2001"),
                         {"account_id": "ACC-2001", "balance": 920.10, "currency": "EUR"})
        self.assertIn("Unknown account ACC-5", await self.fails("get_balance", account_id="ACC-5"))
        self.assertIn("Unknown account C-1001", await self.fails("get_balance", account_id="C-1001"))

    async def test_list_transactions_with_its_defaults_limit_and_category(self):
        self.assertEqual((await self.ok("list_transactions", account_id="ACC-1001"))["count"], 10)
        few = await self.ok("list_transactions", account_id="ACC-1001", limit=2, category="groceries")
        self.assertEqual((few["count"], few["total"]), (2, round(-63.40 - 27.85, 2)))
        self.assertIn("Unknown account ACC-5", await self.fails("list_transactions", account_id="ACC-5"))

    async def test_transfer_funds(self):
        done = await self.ok("transfer_funds", from_account="ACC-1001", to_account="ACC-2001", amount=120.5,
                             reference="lunch")
        self.assertEqual((done["confirmation_id"], done["new_balance"], done["reference"]),
                         ("TRF-000001", 4700.05, "lunch"))
        self.assertEqual((await self.ok("get_balance", account_id="ACC-2001"))["balance"], 1040.60)

    async def test_transfer_funds_refuses_what_cannot_happen(self):
        cases = [({"from_account": "ACC-2001", "to_account": "ACC-1001", "amount": 1000}, "Insufficient funds"),
                 ({"from_account": "ACC-2001", "to_account": "ACC-2001", "amount": 1}, "two different accounts"),
                 ({"from_account": "ACC-2001", "to_account": "ACC-7", "amount": 1}, "Unknown account ACC-7"),
                 ({"from_account": "ACC-2001", "to_account": "ACC-1001", "amount": 1.234}, "two decimals")]
        for arguments, expected in cases:
            with self.subTest(expected=expected):
                self.assertIn(expected, await self.fails("transfer_funds", **arguments))
        self.assertEqual((await self.ok("get_balance", account_id="ACC-2001"))["balance"], 920.10)

    async def test_amounts_are_strict_json_numbers(self):
        for bad in ("12000", "120", True, False, None, 0, -5):
            with self.subTest(amount=bad):
                self.assertIn("transfer_funds", await self.fails("transfer_funds", amount=bad, **MOVE))
        self.assertEqual((await self.ok("get_balance", account_id="ACC-9001"))["balance"], 25000)
        for good in (12000, 12000.0, 0.5):
            with self.subTest(amount=good):
                await self.ok("transfer_funds", amount=good, **MOVE)

    async def test_a_loan_amount_is_strict_too(self):
        await self.fails("simulate_loan", amount="10000", years=5)
        self.assertEqual((await self.ok("simulate_loan", amount=10000, years=5))["annual_rate_percent"], 4.2)

    async def test_freeze_card(self):
        frozen = await self.ok("freeze_card", card_id="CARD-2001", reason="stolen")
        self.assertEqual((frozen["status"], frozen["previous_status"], frozen["reason"]),
                         ("FROZEN", "ACTIVE", "stolen"))
        self.assertIn("Unknown card CARD-5", await self.fails("freeze_card", card_id="CARD-5", reason="x"))
        await self.fails("freeze_card", card_id="CARD-2001")  # a reason is required

    async def test_get_exchange_rate(self):
        self.assertEqual((await self.ok("get_exchange_rate", base="EUR", quote="USD", amount=1))["rate"], 1.0842)
        self.assertIn("Unsupported currency", await self.fails("get_exchange_rate", base="EUR", quote="XYZ", amount=1))
        self.assertIn("amount", await self.fails("get_exchange_rate", base="EUR", quote="USD"))

    async def test_get_exchange_rate_with_an_amount_converts_it(self):
        converted = await self.ok("get_exchange_rate", base="EUR", quote="USD", amount=2500)
        self.assertEqual((converted["rate"], converted["converted"]), (1.0842, 2710.50))
        self.assertEqual((await self.ok("get_exchange_rate", base="eur", quote="usd", amount=1250.50))["converted"],
                         1355.79)

    async def test_the_amount_to_convert_is_a_strict_number_above_zero(self):
        for bad in ("2500", True, 0, -5):
            with self.subTest(amount=bad):
                self.assertIn("get_exchange_rate",
                              await self.fails("get_exchange_rate", base="EUR", quote="USD", amount=bad))

    async def test_simulate_loan(self):
        loan = await self.ok("simulate_loan", amount=10000, years=5, annual_rate_percent=4.2)
        self.assertEqual((loan["monthly_payment"], loan["total_cost"]), (185.07, 11104.15))
        self.assertIn("duration", await self.fails("simulate_loan", amount=10000, years=0))

    async def test_find_branches(self):
        self.assertEqual((await self.ok("find_branches", city="Lyon"))["branches"][0]["id"], "lyon-bellecour")
        self.assertEqual((await self.ok("find_branches", city="Atlantis"))["count"], 0)

    async def test_an_unknown_tool_is_an_error_result(self):
        self.assertIn("no_such_tool", await self.fails("no_such_tool"))


class Logging(Case):
    async def test_one_line_per_request_naming_the_tool_and_never_its_arguments(self):
        with self.assertLogs("bank-mcp", "INFO") as logs:
            async with Client(srv.mcp) as c:
                await c.list_tools()
                await c.call_tool("transfer_funds", {"from_account": "ACC-1001", "to_account": "ACC-2001",
                                                     "amount": 123.45, "reference": "private note"})
                await c.call_tool("get_balance", {"account_id": "ACC-5"})
                await c.read_resource("acme://policies/fees")
        lines = [record.getMessage().split(" in ")[0] for record in logs.records]
        self.assertEqual([line for line in lines if not line.startswith(("initialize", "server/discover"))],
                         ["tools/list -> ok", "tools/call transfer_funds -> ok", "tools/call get_balance -> tool error",
                          "resources/read acme://policies/fees -> ok"])
        for secret in ("ACC-1001", "ACC-2001", "123.45", "private note"):
            self.assertNotIn(secret, "\n".join(logs.output))


class OverHttp(Case):
    def client(self, http, **options):
        return Client(streamable_http_client(options.pop("url", URL), http_client=http), **options)

    async def test_health(self):
        async with served() as http:
            answer = await http.get("/health")
        self.assertEqual((answer.status_code, answer.json()), (200, {"status": "ok"}))

    async def test_each_protocol_era_negotiates_and_serves_the_tools(self):
        async with served() as http:
            for mode, expected in ERAS.items():
                with self.subTest(mode=mode):
                    async with self.client(http, mode=mode) as c:
                        self.assertEqual(c.protocol_version, expected)
                        self.assertEqual([t.name for t in (await c.list_tools()).tools], TOOLS)
                        balance = self.data(await c.call_tool("get_balance", {"account_id": "ACC-1002"}))
                        self.assertEqual(balance["balance"], 15300)

    async def test_the_client_url_works_with_or_without_a_trailing_slash(self):
        async with served() as http:
            for url in ("http://bank-mcp:8000", "http://bank-mcp:8000/"):
                with self.subTest(url=url):
                    async with self.client(http, url=url) as c:
                        self.assertEqual(len((await c.list_tools()).tools), 8)

    async def test_a_strict_amount_is_refused_over_the_wire_in_both_eras(self):
        async with served() as http:
            for mode in ("legacy", "2026-07-28"):
                with self.subTest(mode=mode):
                    async with self.client(http, mode=mode) as c:
                        self.error(await c.call_tool("transfer_funds", {**MOVE, "amount": "12000"}))
                        self.data(await c.call_tool("transfer_funds", {**MOVE, "amount": 12000}))

    async def test_a_call_needs_no_initialize_and_no_session_and_comes_back_as_json(self):
        """What the gateway and the traffic generator rely on: every call stands alone, and the answer is not a stream.
        A raw request, so that no client option can hide a change of the server's transport options."""
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "get_balance", "arguments": {"account_id": "ACC-1002"}}}
        async with served() as http:
            answer = await http.post("/", json=call, headers={"Accept": "application/json, text/event-stream"})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.headers["content-type"], "application/json")
        self.assertNotIn("mcp-session-id", answer.headers)
        self.assertEqual(answer.json()["result"]["structuredContent"]["balance"], 15300)


class Names(Case):
    """A page on a hostile name that points at this machine (DNS rebinding) sends that name as its Host, a browser sends
    an Origin with a call it makes, and a cross-site call that skips the preflight can only carry a plain text body."""

    CALL = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    ACCEPT = {"Accept": "application/json, text/event-stream"}

    async def ask(self, hosts="bank-mcp", **headers):
        async with served(hosts) as http:
            return await http.post("/", json=self.CALL, headers={**self.ACCEPT, **headers})

    async def test_the_names_of_the_container_and_of_this_machine_are_served(self):
        for hosts, host in (("bank-mcp", "bank-mcp:8000"), ("bank-mcp", "bank-mcp"), ("bank-mcp,localhost", "localhost:8111"),
                            ("", "localhost:8111"), ("", "127.0.0.1:8111"), ("", "[::1]:8111"), ("A.test", "a.test:8000")):
            with self.subTest(host=host, hosts=hosts):
                self.assertEqual((await self.ask(hosts, Host=host)).status_code, 200)

    async def test_any_other_name_is_refused_before_a_tool_is_reached(self):
        for host in ("evil.example:8000", "evil.example", "bank-mcp.evil.example:8000", "localhost.evil.example:8111",
                     "127.0.0.1.evil.example:8111"):
            with self.subTest(host=host):
                self.assertEqual((await self.ask(Host=host)).status_code, 421)

    async def test_without_a_setting_only_this_machine_is_served_so_the_container_name_is_a_setting(self):
        self.assertEqual((await self.ask("", Host="bank-mcp:8000")).status_code, 421)
        self.assertEqual((await self.ask("bank-mcp", Host="bank-mcp:8000")).status_code, 200)

    async def test_a_page_of_another_origin_is_refused_whatever_its_host(self):
        for origin in ("http://evil.example", "http://evil.example:8000", "null", "http://bank-mcp.evil.example"):
            with self.subTest(origin=origin):
                self.assertEqual((await self.ask(Host="bank-mcp:8000", Origin=origin)).status_code, 403)
        for origin in ("http://bank-mcp:8000", "http://bank-mcp"):
            with self.subTest(origin=origin):
                self.assertEqual((await self.ask(Host="bank-mcp:8000", Origin=origin)).status_code, 200)

    async def test_a_plain_text_body_is_no_call(self):
        async with served() as http:
            answer = await http.post("/", content=json.dumps(self.CALL), headers={**self.ACCEPT, "Content-Type": "text/plain"})
        self.assertEqual(answer.status_code, 400)

    async def test_the_names_are_a_comma_separated_list_without_ports(self):
        options = srv.http_options(" bank-mcp , Gateway.Test ,")["transport_security"]
        self.assertEqual(options.allowed_hosts, ["bank-mcp", "bank-mcp:*", "gateway.test", "gateway.test:*"])
        self.assertIn("https://gateway.test:*", options.allowed_origins)
        self.assertEqual(srv.http_options()["transport_security"].allowed_hosts[::2], list(srv.DEFAULT_HOSTS))

    async def test_the_server_still_listens_on_every_interface(self):
        self.assertEqual(srv.http_options()["host"], "0.0.0.0")


class Admin(Case):
    """POST /admin/reset is the one route that is not MCP. The gateway's MCP proxy answers 404 to every path but its
    root, so only a request that goes around the gateway reaches it: the route protects itself with a token."""

    async def reset_after_a_transfer(self, headers, token=TOKEN):
        """The answer of the reset and the balance of ACC-1001 after it, once a transfer took EUR 600 from it."""
        srv.BANK.reset()
        with admin_token(token):
            async with served() as http:
                async with Client(streamable_http_client(URL, http_client=http)) as c:
                    await c.call_tool("transfer_funds", {"from_account": "ACC-1001", "to_account": "ACC-2001",
                                                         "amount": 600})
                    answer = await http.post("/admin/reset", headers=headers)
                    balance = self.data(await c.call_tool("get_balance", {"account_id": "ACC-1001"}))["balance"]
        return answer, balance

    async def test_reset_with_the_token_restores_the_starting_data(self):
        answer, balance = await self.reset_after_a_transfer({"X-Admin-Token": TOKEN})
        self.assertEqual((answer.status_code, answer.json()), (200, {"status": "reset"}))
        self.assertEqual(balance, 4820.55)

    async def test_reset_brings_a_frozen_card_back(self):
        with admin_token(TOKEN):
            async with served() as http:
                async with Client(streamable_http_client(URL, http_client=http)) as c:
                    await c.call_tool("freeze_card", {"card_id": "CARD-1001", "reason": "stolen"})
                    await http.post("/admin/reset", headers={"X-Admin-Token": TOKEN})
                    frozen = self.data(await c.call_tool("freeze_card", {"card_id": "CARD-1001", "reason": "stolen"}))
        self.assertEqual(frozen["previous_status"], "ACTIVE")

    async def test_reset_without_the_right_token_is_refused_and_changes_nothing(self):
        for headers in ({}, {"X-Admin-Token": ""}, {"X-Admin-Token": "wrong"}, {"X-Admin-Token": TOKEN + "x"},
                        {"X-Admin-Token": TOKEN[:-1]}, {"X-Admin-Token": TOKEN.upper()}, {"Authorization": TOKEN}):
            with self.subTest(headers=headers):
                answer, balance = await self.reset_after_a_transfer(headers)
                self.assertEqual(answer.status_code, 403)
                self.assertEqual(answer.json()["error"], "forbidden")
                self.assertEqual(balance, 4220.55)

    async def test_reset_is_off_when_the_server_has_no_token(self):
        for token in (None, ""):
            for headers in ({}, {"X-Admin-Token": ""}, {"X-Admin-Token": "anything"}):
                with self.subTest(token=token, headers=headers):
                    answer, balance = await self.reset_after_a_transfer(headers, token)
                    self.assertEqual((answer.status_code, balance), (403, 4220.55))

    async def test_a_refused_reset_is_logged_without_the_token_it_was_given(self):
        with self.assertLogs("bank-mcp", "WARNING") as logs, admin_token(TOKEN):
            async with served() as http:
                await http.post("/admin/reset", headers={"X-Admin-Token": "a-guess"})
        self.assertEqual(len(logs.records), 1)
        self.assertIn("admin/reset -> refused: the X-Admin-Token header is missing or wrong", logs.output[0])
        self.assertNotIn("a-guess", logs.output[0])

    async def test_a_server_without_a_token_says_so_when_it_refuses(self):
        with self.assertLogs("bank-mcp", "WARNING") as logs, admin_token(None):
            async with served() as http:
                await http.post("/admin/reset", headers={"X-Admin-Token": "a-guess"})
        self.assertIn("admin/reset -> refused: ADMIN_TOKEN is not set on this server", logs.output[0])
        self.assertNotIn("a-guess", logs.output[0])

    async def test_reset_is_a_post(self):
        with admin_token(TOKEN):
            async with served() as http:
                self.assertEqual((await http.get("/admin/reset", headers={"X-Admin-Token": TOKEN})).status_code, 405)


if __name__ == "__main__":
    unittest.main()
