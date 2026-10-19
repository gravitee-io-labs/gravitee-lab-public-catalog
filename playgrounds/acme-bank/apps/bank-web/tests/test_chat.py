"""The chat: what reaches Ace, and how its trace becomes the Behind the answer panel."""

import base64
import json
from urllib.parse import parse_qs, urlsplit

import httpx

from starlette.responses import JSONResponse, PlainTextResponse

from tests.base import AppCase
from tests.fakes import bearer_claims

DENIED = (
    "I cannot show that account.",
    [
        {"step": "llm", "name": "acme-chat", "outcome": "ok", "ms": 300, "status": 200},
        {
            "step": "tool",
            "name": "list_accounts",
            "arguments": {"customer_id": "C-1001"},
            "outcome": "denied",
            "detail": "Not allowed by ACME authorization policy",
            "status": 403,
            "ms": 9,
            "transaction_id": "tx-9",
            "request_id": "req-tool-9",
        },
    ],
    None,
)


def query_of(link: str) -> dict:
    """The filter the console would read from a link: the `q` parameter, decoded."""
    q = parse_qs(urlsplit(link).query)["q"][0]
    return json.loads(base64.urlsafe_b64decode(q + "=" * (-len(q) % 4)))


class Question(AppCase):
    async def test_the_question_reaches_ace_with_the_users_own_token(self):
        await self.sign_in("alice")
        out = await self.chat("Show my accounts and balances")
        self.assertEqual(out["answer"], "Your balance is EUR 4,820.55.")
        asked = self.world.ace.log[0]
        self.assertEqual(asked["text"], "Show my accounts and balances")
        self.assertEqual(bearer_claims(asked["authorization"])["username"], "alice@acme-bank.test")
        self.assertEqual(asked["a2a_version"], "1.0")

    async def test_the_answer_is_the_call_to_ace_and_then_each_call_ace_made_in_the_order_it_made_them(self):
        """The first hop is the answer's own call (the person asking Ace, through the A2A proxy); then the real Ace's: its token, its tools, the model that
        chooses, the tool, the model that writes the answer."""
        await self.sign_in("alice")
        out = await self.chat()
        self.assertEqual([r["title"] for r in out["rows"]], [
            "Alice asked Ace", "Ace got a token for Alice", "Ace asked which tools it may use", "Ace asked the model what to do", "Ace called get_balance",
            "Ace asked the model for the answer"])
        self.assertEqual([r["system"] for r in out["rows"]], ["A2A proxy", "Access Management", "MCP proxy", "LLM proxy", "MCP proxy", "LLM proxy"])
        self.assertEqual([r["status"] for r in out["rows"]], [200] * 6)
        self.assertEqual([r["word"] for r in out["rows"]], ["Answered"] * 6)
        self.assertEqual([r["summary"] for r in out["rows"]], [
            "Ace answered after the 5 calls below.", "Access Management issued it: sub Alice, acting agent ace-agent.", "Ace may use 7 of 8 tools, not freeze_card.",
            "The model chose get_balance.", "The bank's tool answered.", "The model wrote the answer."])
        self.assertEqual((out["rows"][3]["ms"], out["rows"][5]["ms"]), (410, 655))
        for row in out["rows"]:
            self.assertIn("evidence", row)
        self.assertNotIn("evidence", out, "the evidence is each hop's own, none is the answer's")
        self.assertNotIn("tools", out, "what Ace may use is said by the hop that listed the tools")

    async def test_each_hop_that_went_through_the_gateway_carries_the_ids_of_its_own_request(self):
        await self.sign_in("alice")
        a2a, exchange, tools, first, tool, second = (await self.chat())["rows"]
        self.assertEqual((a2a["api"], a2a["request_id"].startswith("req-a2a-"), a2a["transaction_id"].startswith("tx-a2a-")), ("a2a", True, True))
        self.assertEqual((exchange["api"], exchange["request_id"], exchange["transaction_id"]), (None, None, None), "Access Management is not behind the gateway")
        self.assertEqual([(r["api"], r["request_id"].startswith(f"req-{step}-")) for r, step in ((tools, "tool"), (first, "llm"), (tool, "tool"), (second, "llm"))],
                         [("mcp", True), ("llm", True), ("mcp", True), ("llm", True)])
        ids = [r["request_id"] for r in (a2a, tools, first, tool, second)]
        self.assertEqual(len(set(ids)), 5, "five calls, five requests: none is another's")
        self.assertNotIn("must-not-show", str((await self.chat("again"))["rows"]))        # a secret in the arguments is never shown

    async def test_the_buttons_of_each_hop_are_those_of_its_own_call(self):
        await self.sign_in("alice")
        out = await self.chat()
        for row in out["rows"]:
            for e in row["evidence"]:
                found = parse_qs(urlsplit(e["url"]).query)
                self.assertEqual((found["api"], found["request"]), ([row["api"]], [row["request_id"]]), f"{row['title']}: {e['kind']}")
        self.assertEqual([[e["kind"] for e in r["evidence"]] for r in out["rows"]],
                         [["trace", "logs"], [], ["trace", "logs"], ["trace", "logs"], ["trace", "logs", "decisions"], ["trace", "logs"]])
        self.assertEqual([e["label"] for e in out["rows"][4]["evidence"]], ["Trace", "Logs", "Decisions"])

    async def test_a_denial_shows_the_gateways_message_and_the_request_its_decision_is_filed_under(self):
        await self.sign_in("bob")
        self.world.ace.reply = DENIED
        out = await self.chat("Show the accounts of customer C-1001")
        tool = out["rows"][-1]
        self.assertEqual((tool["tone"], tool["word"], tool["status"], tool["system"]), ("deny", "Denied by policy", 403, "MCP proxy"))
        self.assertEqual(tool["summary"], "Denied by policy: Not allowed by ACME authorization policy")
        self.assertEqual((tool["request_id"], tool["transaction_id"]), ("req-tool-9", "tx-9"))
        decision = next(e for e in tool["evidence"] if e["kind"] == "decisions")
        self.assertEqual(parse_qs(urlsplit(decision["url"]).query)["request"], ["req-tool-9"])

    async def test_blocked_limited_and_failed_hops_are_loud_and_say_why(self):
        await self.sign_in("alice")
        trace = [
            {"step": "llm", "outcome": "blocked", "detail": "AI prompt validation detected", "status": 400, "blocked_by": "llm-proxy"},
            {"step": "llm", "outcome": "rate_limited", "status": 429},
            {"step": "tool", "name": "freeze_card", "outcome": "unauthorized", "status": 401},
            {"step": "tool", "name": "transfer_funds", "outcome": "error", "detail": "Insufficient funds"},
            {"step": "exchange", "outcome": "ok", "ms": 12},
            {"step": "llm", "outcome": "something new"},
        ]
        self.world.ace.reply = ("Done.", trace, None)
        rows = (await self.chat())["rows"][1:]
        self.assertEqual([(r["tone"], r["word"]) for r in rows],
                         [("block", "Blocked"), ("limit", "Limited"), ("deny", "Unauthorized"), ("error", "Error"), ("ok", "Answered"), ("note", "something new")])
        self.assertEqual(rows[0]["summary"], "Blocked: AI prompt validation detected")
        self.assertEqual(rows[3]["summary"], "Error: Insufficient funds")
        self.assertEqual(rows[4]["title"], "Ace got a token for Alice")
        self.assertEqual([r["request_id"] for r in rows], [None] * 6)                   # no request id: nothing to find the evidence by
        self.assertEqual([r["evidence"] for r in rows], [[]] * 6, "and so no button that goes nowhere")

    async def test_what_ace_may_use_is_the_list_ace_was_given_out_of_every_tool_the_bank_has(self):
        """Ace reports the tools it was offered with its answer: no call of the app's own through the gateway, and the same count on every answer."""
        await self.sign_in("alice")
        out = await self.chat()
        self.assertEqual(out["rows"][2]["summary"], "Ace may use 7 of 8 tools, not freeze_card.")
        self.assertEqual(self.world.mcp.log, [], "the proxy was asked nothing by the app: the list is Ace's own")
        self.assertEqual([m["method"] for m in self.world.bank.mcp.log], ["tools/list"], "the bank's catalog is read once, directly")
        await self.chat("again")
        self.assertEqual(len(self.world.bank.mcp.log), 1, "and kept")

    async def test_the_tools_are_those_ace_lists_at_each_question_so_a_filter_switched_on_shows_at_once(self):
        await self.sign_in("alice")
        self.world.controls.tools = False
        self.assertEqual((await self.chat())["rows"][2]["summary"], "Ace may use 8 of 8 tools.")
        self.world.controls.tools = True
        self.assertEqual((await self.chat("Again"))["rows"][2]["summary"], "Ace may use 7 of 8 tools, not freeze_card.")

    async def test_a_teller_may_use_every_tool(self):
        await self.sign_in("tina")
        self.assertEqual((await self.chat())["rows"][2]["summary"], "Ace may use 8 of 8 tools.")

    async def test_the_tools_ace_was_offered_are_in_the_details_of_the_hop_that_listed_them(self):
        await self.sign_in("alice")
        facts = (await self.chat())["rows"][2]["facts"]
        self.assertEqual([f["label"] for f in facts], ["Offered"])
        self.assertNotIn("freeze_card", facts[0]["value"])
        self.assertIn("transfer_funds", facts[0]["value"])

    async def test_the_conversation_goes_on_with_the_same_context(self):
        await self.sign_in("alice")
        await self.chat("one")
        await self.chat("two")
        first, second = self.world.ace.log
        self.assertIsNotNone(second["context_id"])
        self.assertEqual(first["context_id"], second["context_id"])

    async def test_delegated_claims_are_kept_for_the_tokens_drawer(self):
        await self.sign_in("alice")
        claims = {"sub": "id-alice", "act": {"sub": "ace-agent"}, "role": "customer"}
        self.world.ace.reply = ("ok", [], claims)
        out = await self.chat()
        self.assertEqual(out["delegated_claims"], claims)
        tokens = (await self.http.get("/api/tokens")).json()
        self.assertEqual(tokens["delegated"]["act"]["sub"], "ace-agent")
        self.assertEqual(tokens["user"]["name"], "Alice Martin")

    async def test_a_log_line_names_the_hops_and_never_the_question_the_token_or_the_arguments(self):
        await self.sign_in("alice")
        with self.assertLogs("bank-web", level="INFO") as logs:
            await self.chat("What is the balance of ACC-2001?")
        text = "\n".join(logs.output)
        self.assertIn("Ace called get_balance:Answered", text)
        for secret in ("ACC-2001", "ACC-1001", "must-not-show", "balance of"):
            self.assertNotIn(secret, text)


class WithoutTheGateway(AppCase):
    async def test_the_same_question_goes_to_the_agent_without_a_gateway_and_says_so(self):
        await self.sign_in("bob")
        self.world.direct_ace.reply = (
            "Alice has ACC-1001 and ACC-1002.",
            [
                {
                    "step": "tool",
                    "name": "list_accounts",
                    "arguments": {"customer_id": "C-1001"},
                    "outcome": "ok",
                    "ms": 5,
                }
            ],
            None,
        )
        out = await self.chat("Show the accounts of customer C-1001", gateway="off")
        self.assertEqual((out["gateway"], out["protected"]), ("off", False))
        self.assertEqual(len(self.world.direct_ace.log), 1)
        self.assertEqual(self.world.ace.log, [])
        self.assertEqual([r["title"] for r in out["rows"]], ["Bob asked Ace", "Ace called list_accounts"])      # the answer's own call first, as with the gateway
        self.assertEqual([(r["system"], r["direct"], r["request_id"], r["evidence"]) for r in out["rows"]], [("No gateway", True, None, [])] * 2, "nothing was recorded: no button")
        self.assertEqual(out["rows"][0]["status"], 200)
        self.assertEqual(self.world.mcp.log, [])  # the proxy was not asked

    async def test_each_mode_keeps_its_own_conversation(self):
        await self.sign_in("alice")
        await self.chat("one")
        await self.chat("two", gateway="off")
        await self.chat("three")
        self.assertEqual(self.world.ace.log[0]["context_id"], self.world.ace.log[1]["context_id"])
        self.assertNotEqual(self.world.direct_ace.log[0]["context_id"], self.world.ace.log[0]["context_id"])

    async def test_delegation_is_shown_only_when_the_gateway_is_on(self):
        await self.sign_in("alice")
        self.world.ace.reply = ("ok", [], {"sub": "id-alice", "act": {"sub": "ace-agent"}})
        await self.chat()
        await self.chat(gateway="off")
        self.assertIsNone((await self.http.get("/api/tokens")).json()["delegated"])


class WhenAceDoesNotAnswer(AppCase):
    async def test_a_gateway_timeout_says_ace_is_not_answering(self):
        await self.sign_in("alice")
        self.world.gateway_ace.refuse_with = 504
        response = await self.http.post("/api/chat", json={"message": "hi"})
        self.assertEqual(
            (response.status_code, response.json()["error"]), (504, "Ace is not answering. Try again in a minute.")
        )
        self.assertEqual((await self.http.get("/api/session")).json()["persona"], "alice")  # still signed in

    async def test_a_call_the_gateway_answered_with_a_failure_is_a_hop_with_its_own_buttons(self):
        """The gateway answered, so the call went through it: Behind the answer shows it, with the Logs of that very request (a refused call is in them too)."""
        await self.sign_in("alice")
        self.world.gateway_ace.refuse_with = 504
        response = await self.http.post("/api/chat", json={"message": "hi"})
        (row,) = response.json()["rows"]
        self.assertEqual((row["title"], row["system"], row["status"], row["tone"], row["word"]), ("Alice asked Ace", "A2A proxy", 504, "error", "Error"))
        self.assertEqual(row["summary"], "Error: Unauthorized")        # what the gateway said, as it said it
        self.assertEqual([e["kind"] for e in row["evidence"]], ["trace", "logs"])
        self.assertTrue(row["request_id"].startswith("req-a2a-"))

    async def test_a_refused_sign_in_is_the_a2a_proxy_refusing_with_a_401_and_its_logs(self):
        await self.sign_in("alice")
        self.world.gateway_ace.refuse_with = 401
        (row,) = (await self.http.post("/api/chat", json={"message": "hi"})).json()["rows"]
        self.assertEqual((row["status"], row["tone"], row["word"]), (401, "deny", "Unauthorized"))
        self.assertEqual(row["summary"], "Unauthorized.")

    async def test_an_answer_that_never_came_has_no_hop_of_the_gateways(self):
        """No answer of the gateway that is a failure (an answer that is no A2A answer was a 200; a host that is down said nothing): the page draws the one hop it has."""
        await self.sign_in("alice")
        self.world.gateway_ace.answer_with = JSONResponse({"hello": "world"})
        with self.assertLogs("bank-web.chat", level="WARNING"):
            self.assertNotIn("rows", (await self.http.post("/api/chat", json={"message": "hi"})).json())
        self.world.transport.hosts.pop("gateway.test")
        self.assertNotIn("rows", (await self.http.post("/api/chat", json={"message": "hi"})).json())

    async def test_a_token_the_gateway_refuses_ends_that_persons_sign_in_and_the_answer_says_who_is_signed_in_now(self):
        await self.sign_in("alice")
        self.world.gateway_ace.refuse_with = 401
        response = await self.http.post("/api/chat", json={"message": "hi"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("Sign in again", response.json()["error"])
        self.assertEqual(response.json()["who"], {"persona": None, "signed": []})
        self.assertEqual((await self.http.get("/api/session")).json(), {"persona": None, "signed": []})

    async def test_an_answer_that_is_no_a2a_answer_is_the_same_message_and_the_session_stays(self):
        await self.sign_in("alice")
        rpc = {"jsonrpc": "2.0", "id": "1"}
        for what, answer in (
            ("a JSON-RPC error", JSONResponse({**rpc, "error": {"code": -32603, "message": "boom"}})),
            ("a JSON object that is no JSON-RPC answer", JSONResponse({"hello": "world"})),
            ("a JSON list", JSONResponse([1, 2])),
            ("a result that is no A2A message", JSONResponse({**rpc, "result": {"nonsense": 1}})),
            ("a page of text", PlainTextResponse("<html>Welcome</html>")),
        ):
            with self.subTest(what), self.assertLogs("bank-web.chat", level="WARNING") as logs:
                self.world.gateway_ace.answer_with = answer
                response = await self.http.post("/api/chat", json={"message": "hi"})
                self.assertEqual(
                    (response.status_code, response.json()["error"]), (502, "Ace is not answering. Try again in a minute.")
                )
                self.assertIn("the A2A call failed", logs.output[0])
            self.assertEqual((await self.http.get("/api/session")).json()["persona"], "alice")

    async def test_an_agent_that_fails_while_it_answers_is_the_same_message(self):
        await self.sign_in("alice")
        self.world.ace.fails_with = RuntimeError("the model is gone")
        with self.assertLogs("a2a", level="ERROR"):  # Ace's own server logs its failure
            response = await self.http.post("/api/chat", json={"message": "hi"})
        self.assertEqual(
            (response.status_code, response.json()["error"]), (502, "Ace is not answering. Try again in a minute.")
        )
        self.assertNotIn("the model is gone", response.text)

    async def test_a_host_that_is_down_is_the_same_message(self):
        await self.sign_in("alice")
        self.world.transport.hosts.pop("gateway.test")
        response = await self.http.post("/api/chat", json={"message": "hi"})
        self.assertEqual(
            (response.status_code, response.json()["error"]), (502, "Ace is not answering. Try again in a minute.")
        )


class Asking(AppCase):
    async def test_a_bad_question_is_refused_before_it_goes_anywhere(self):
        await self.sign_in("alice")
        for body in (
            {},
            {"message": "  "},
            {"message": 3},
            {"message": "x" * 2001},
            {"message": "hi", "gateway": "maybe"},
        ):
            response = await self.http.post("/api/chat", json=body)
            self.assertEqual(response.status_code, 400, body)
        self.assertEqual((await self.http.post("/api/chat", content=b"not json")).status_code, 400)
        self.assertEqual((await self.http.post("/api/chat", json=["a"])).status_code, 400)
        self.assertEqual(self.world.ace.log, [])


class WhoAnswers(AppCase):
    """The session cookie is shared by the tabs of a browser: an answer says whose it is, so that another tab's choice is not taken for this one's."""

    async def test_a_question_and_a_payment_come_back_with_the_person_who_made_them(self):
        await self.sign_in("alice")
        asked = await self.chat()
        self.assertEqual(asked["who"], {"persona": "alice", "name": "Alice Martin", "role": "customer", "signed": ["alice"]})
        paid = await self.http.post("/api/send-money", json={"from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 5})
        self.assertEqual(paid.json()["who"]["persona"], "alice")

    async def test_the_person_another_tab_chose_is_the_one_who_answers_and_the_answer_says_so(self):
        await self.sign_in("alice")
        other = self.browser()
        other.cookies = httpx.Cookies(self.http.cookies)                        # the same browser: one cookie jar for two tabs
        self.addAsyncCleanup(other.aclose)
        await self.sign_in("tina", other)                                       # the other tab chooses somebody else: the cookie is replaced
        self.http.cookies = httpx.Cookies(other.cookies)
        answered = await self.chat()
        self.assertEqual(answered["who"]["persona"], "tina")

    async def test_a_catalog_of_tools_that_cannot_be_read_does_not_fail_the_turn(self):
        """"Ace may use N of M tools" is counted out of what the bank's server has: when that cannot be read the answer still comes, with the count of Ace's own list."""
        await self.sign_in("alice")
        self.world.bank.mcp.fail_list = True
        answered = await self.chat()
        self.assertEqual(answered["answer"], "Your balance is EUR 4,820.55.")
        self.assertEqual(answered["rows"][2]["summary"], "Ace may use 7 tools.")
        self.world.bank.mcp.fail_list = False
        self.assertEqual((await self.chat("Again"))["rows"][2]["summary"], "Ace may use 7 of 8 tools, not freeze_card.")
