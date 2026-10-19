"""Ace over A2A 1.0, with the real SDK client and the real app, in memory."""
import json
import os
import unittest
from dataclasses import replace
from unittest import mock

import httpx
from a2a.client import ClientCallContext, ClientConfig, create_client
from a2a.helpers import get_data_parts, get_message_text, new_message, new_text_part
from a2a.types import Role, SendMessageRequest

from chat import Reply
from server import bearer_of, build_app, main
from settings import Settings
from tests.fakes import BEHIND_THE_GATEWAY, World, alice_token, completion, tool_call

BASE = "http://bank-agent:8000"
TRACE = [{"step": "llm", "name": "acme-chat", "outcome": "ok", "ms": 12}]


class FakeAce:
    """Stands in for the loop: what the executor hands it, what it answers."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.transactions: list[str | None] = []
        self.closed = False

    async def reply(self, question, bearer, transaction_id=None):
        self.calls.append((question, bearer))
        self.transactions.append(transaction_id)
        return Reply("Hello from Ace.", {"trace": TRACE, "tools": ["get_balance"]})

    async def aclose(self):
        self.closed = True


async def send(app, text, token=None, context_id=None, authorization=None, transaction=None):
    """One SendMessage, as bank-web sends it: a local client, the token on the call."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http:
        client = await create_client(BASE, client_config=ClientConfig(httpx_client=http, streaming=False))
        request = SendMessageRequest(message=new_message([new_text_part(text)], role=Role.ROLE_USER, context_id=context_id))
        headers = {"Authorization": authorization or f"Bearer {token}"} if (token or authorization) else {}
        if transaction:
            headers["X-Gravitee-Transaction-Id"] = transaction
        responses = [r async for r in client.send_message(request, context=ClientCallContext(service_parameters=headers))]
        await client.close()
    assert len(responses) == 1
    return responses[0].message


class Card(unittest.IsolatedAsyncioTestCase):
    async def test_health_and_the_agent_card(self):
        app = build_app(BEHIND_THE_GATEWAY, FakeAce())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http:
            self.assertEqual((await http.get("/health")).json(), {"status": "ok"})
            card = (await http.get("/.well-known/agent-card.json")).json()
        self.assertEqual(card["name"], "Ace")
        self.assertEqual(card["supportedInterfaces"],
                         [{"url": "http://bank-agent:8000", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}])
        self.assertNotIn("url", card)                                       # A2A 1.0 has no top-level url
        self.assertEqual([s["id"] for s in card["skills"]], ["accounts", "payments", "cards", "rates"])
        self.assertTrue(all(s["examples"] and s["tags"] for s in card["skills"]))
        self.assertEqual(card["capabilities"].get("streaming", False), False)
        self.assertEqual(card["defaultOutputModes"], ["text/plain", "application/json"])

    async def test_the_legacy_card_path_serves_the_same_card(self):
        """The A2A proxy answers 500 when a path it probes is a 404 at the agent."""
        app = build_app(BEHIND_THE_GATEWAY, FakeAce())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http:
            card, legacy = await http.get("/.well-known/agent-card.json"), await http.get("/.well-known/agent.json")
        self.assertEqual((card.status_code, legacy.status_code), (200, 200))
        self.assertEqual(legacy.json(), card.json())
        self.assertEqual(legacy.json()["name"], "Ace")

    async def test_the_card_says_where_clients_call_ace(self):
        settings = replace(BEHIND_THE_GATEWAY, public_url="http://localhost:8082/acme-bank/ace/")
        app = build_app(settings, FakeAce())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http:
            card = (await http.get("/.well-known/agent-card.json")).json()
        self.assertEqual(card["supportedInterfaces"][0]["url"], "http://localhost:8082/acme-bank/ace/")


class Messages(unittest.IsolatedAsyncioTestCase):
    async def test_a_text_part_for_the_answer_and_a_data_part_for_the_trace_and_no_task(self):
        ace = FakeAce()
        app = build_app(BEHIND_THE_GATEWAY, ace)
        message = await send(app, "What is my balance?", token="the-token", context_id="chat-1")
        self.assertEqual(get_message_text(message), "Hello from Ace.")
        (data,) = get_data_parts(message.parts)
        self.assertEqual(data["tools"], ["get_balance"])
        self.assertEqual([(r["step"], r["name"]) for r in data["trace"]], [("llm", "acme-chat")])
        self.assertEqual(data["trace"][0]["ms"], 12)                         # a float on the wire: 12.0
        self.assertIsInstance(data["trace"][0]["ms"], float)
        self.assertEqual(message.task_id, "")                                # a task id would break the next turn
        self.assertEqual(message.context_id, "chat-1")
        self.assertEqual(ace.calls, [("What is my balance?", "the-token")])

    async def test_a_conversation_goes_on_with_the_same_context(self):
        ace = FakeAce()
        app = build_app(BEHIND_THE_GATEWAY, ace)
        first = await send(app, "Hello", token="t", context_id="chat-1")
        second = await send(app, "And now?", token="t", context_id=first.context_id)
        self.assertEqual((second.context_id, [c[0] for c in ace.calls]), ("chat-1", ["Hello", "And now?"]))

    async def test_a_request_without_a_message_context_gets_one(self):
        message = await send(build_app(BEHIND_THE_GATEWAY, FakeAce()), "Hello", token="t")
        self.assertTrue(message.context_id)

    async def test_the_executor_reads_the_bearer_from_the_headers(self):
        ace = FakeAce()
        app = build_app(BEHIND_THE_GATEWAY, ace)
        await send(app, "one", token="abc")
        await send(app, "two")
        await send(app, "three", authorization="Basic abc")
        await send(app, "four", authorization="bearer xyz")
        self.assertEqual([c[1] for c in ace.calls], ["abc", None, None, "xyz"])

    async def test_the_executor_hands_over_the_transaction_id_the_gateway_gave_the_call(self):
        ace = FakeAce()
        app = build_app(BEHIND_THE_GATEWAY, ace)
        await send(app, "one", token="abc", transaction="3fdb8ff5-ce16-40bf-9b8f-f5ce1630bf4e")
        await send(app, "two", token="abc")
        await send(app, "three", token="abc", transaction="not an id; DROP")
        self.assertEqual(ace.transactions, ["3fdb8ff5-ce16-40bf-9b8f-f5ce1630bf4e", None, None])

    async def test_the_clients_are_closed_when_the_container_stops(self):
        ace = FakeAce()
        app = build_app(BEHIND_THE_GATEWAY, ace)
        async with app.router.lifespan_context(app):
            self.assertFalse(ace.closed)
        self.assertTrue(ace.closed)


class RealAce(unittest.IsolatedAsyncioTestCase):
    async def test_a_chat_from_the_a2a_call_to_the_bank_and_back(self):
        world = World(script=[tool_call("list_accounts", customer_id="C-1001"),
                              completion("You have EUR 4820.55 on ACC-1001.")])
        async with world.ace() as ace:
            message = await send(build_app(world.settings, ace), "Show my accounts and balances", token=alice_token())
        self.assertEqual(get_message_text(message), "You have EUR 4820.55 on ACC-1001.")
        (data,) = get_data_parts(message.parts)
        self.assertEqual([r["step"] for r in data["trace"]], ["exchange", "tool", "llm", "tool", "llm"])
        self.assertEqual(data["delegated_claims"]["act"]["sub"], "ace-agent")
        self.assertEqual(len(data["tools"]), 8)


class WholeTurnUnderOneTransaction(unittest.IsolatedAsyncioTestCase):
    async def test_every_call_ace_makes_to_the_gateway_carries_the_transaction_id_of_the_a2a_call(self):
        world = World(script=[tool_call("list_accounts", customer_id="C-1001"), completion("EUR 4820.55.")])
        async with world.ace() as ace:
            message = await send(build_app(world.settings, ace), "Show my accounts and balances", token=alice_token(),
                                 transaction="turn-1")
        (data,) = get_data_parts(message.parts)
        rows = [r for r in data["trace"] if r["step"] in ("llm", "tool")]
        self.assertEqual({r["transaction_id"] for r in rows}, {"turn-1"})                # one filter in Logs: the turn
        self.assertEqual(len({r["request_id"] for r in rows if r["name"] != "acme-chat"}), 2)   # a decision is per request
        self.assertEqual({r["transaction"] for r in world.gateway.requests}, {"turn-1"})
        self.assertEqual({q["headers"].get("x-gravitee-transaction-id") for q in world.llm.requests}, {"turn-1"})


class Guarding(unittest.IsolatedAsyncioTestCase):
    """What keeps a web page out. Ace has no sign-in of its own on the published port: it runs a chat and calls the bank's
    tools for whoever calls, so a page that can make the browser call it must not get an answer."""

    CHAT = {"jsonrpc": "2.0", "id": "1", "method": "SendMessage", "params": {
        "message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "Convert 100 EUR to USD"}]}}}
    UNKNOWN = {"jsonrpc": "2.0", "id": "1", "method": "NoSuchMethod"}   # the JSON-RPC layer answers it, no chat runs
    NOT_FOUND = -32601

    async def post(self, content_type="application/json", host="bank-agent:8000", settings=BEHIND_THE_GATEWAY,
                   body=CHAT, **headers):
        ace = FakeAce()
        app = build_app(settings, ace)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http:
            answer = await http.post("/", content=json.dumps(body), headers={
                "Content-Type": content_type, "Host": host, "A2A-Version": "1.0", **headers})
        return answer, ace.calls

    async def reaches_the_protocol(self, **kwargs):
        """Whether the call got past the guard, to the JSON-RPC layer that answers a method it does not know."""
        answer, calls = await self.post(body=self.UNKNOWN, **kwargs)
        return answer.status_code == 200 and answer.json()["error"]["code"] == self.NOT_FOUND and calls == []

    async def test_a_call_that_is_json_and_by_a_known_name_goes_through(self):
        for content_type in ("application/json", "application/json; charset=utf-8", "Application/JSON",
                             "application/a2a+json"):
            with self.subTest(content_type=content_type):
                self.assertTrue(await self.reaches_the_protocol(content_type=content_type))

    async def test_a_body_a_page_can_send_without_asking_the_browser_is_refused_and_no_chat_runs(self):
        for content_type in ("text/plain", "text/plain;charset=UTF-8", "application/x-www-form-urlencoded",
                             "multipart/form-data; boundary=x", "application/jsonp", "text/json", ""):
            with self.subTest(content_type=content_type):
                answer, calls = await self.post(content_type, Origin="http://evil.example")
                self.assertEqual((answer.status_code, calls), (415, []))
                self.assertIn("application/json", answer.json()["error"])

    async def test_another_name_gets_no_answer_and_no_chat_runs(self):
        for host in ("evil.example:8114", "evil.example", "bank-agent.evil.example:8000", "localhost:8112", ""):
            with self.subTest(host=host):
                answer, calls = await self.post(host=host)
                self.assertEqual((answer.status_code, calls), (421, []))

    async def test_the_card_and_the_legacy_card_answer_to_the_same_names_only(self):
        app = build_app(BEHIND_THE_GATEWAY, FakeAce())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http:
            for path in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
                with self.subTest(path=path):
                    self.assertEqual((await http.get(path, headers={"Host": "bank-agent:8000"})).status_code, 200)
                    self.assertEqual((await http.get(path, headers={"Host": "rebind.example:8000"})).status_code, 421)

    async def test_the_health_check_calls_by_any_name(self):
        app = build_app(BEHIND_THE_GATEWAY, FakeAce())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http:
            self.assertEqual((await http.get("/health", headers={"Host": "rebind.example"})).status_code, 200)

    async def test_the_names_are_a_setting_and_this_machine_is_the_default(self):
        minimum = {"LLM_URL": "http://llm/v1", "LLM_MODEL": "m", "MCP_URL": "http://bank-mcp:8000/", "DELEGATION": "off"}
        this_machine = Settings.from_env(minimum)
        elsewhere = Settings.from_env({**minimum, "ALLOWED_HOSTS": "ace.example"})
        for host, settings, served in (("localhost:8112", this_machine, True), ("127.0.0.1:8114", this_machine, True),
                                       ("[::1]:8112", this_machine, True), ("bank-agent:8000", this_machine, False),
                                       ("ace.example:443", elsewhere, True), ("localhost:8112", elsewhere, False)):
            with self.subTest(host=host, allowed=settings.allowed_hosts):
                answer, _ = await self.post(host=host, settings=settings, body=self.UNKNOWN)
                self.assertEqual(answer.status_code, 200 if served else 421)

    async def test_a_preflight_is_answered_with_no_permission(self):
        app = build_app(BEHIND_THE_GATEWAY, FakeAce())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http:
            answer = await http.options("/", headers={"Origin": "http://evil.example", "Host": "bank-agent:8000",
                                                      "Access-Control-Request-Method": "POST"})
        self.assertNotIn("access-control-allow-origin", answer.headers)
        self.assertGreaterEqual(answer.status_code, 400)


class Bearer(unittest.TestCase):
    def test_only_a_bearer_scheme_is_a_token(self):
        self.assertEqual(bearer_of("Bearer abc.def"), "abc.def")
        self.assertEqual(bearer_of("bearer  abc "), "abc")
        for header in ("", "Bearer", "Bearer ", "Basic abc", "abc"):
            self.assertIsNone(bearer_of(header), header)


class Start(unittest.TestCase):
    def test_a_missing_setting_stops_the_container_with_its_name(self):
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(SystemExit) as stopped:
            main()
        self.assertEqual(stopped.exception.code, "bank-agent: LLM_URL is not set")


if __name__ == "__main__":
    unittest.main()
