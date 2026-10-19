"""Send money: the human path, with the user's own token and no agent."""

import re
import unittest
from unittest import mock

import hops
import mcp_rpc
import money
from people import PERSONAS
from tests.base import AppCase
from tests.fakes import bearer_claims


class SendMoney(AppCase):
    async def send(self, **fields) -> dict:
        body = {"from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 600, **fields}
        response = await self.http.post("/api/send-money", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_alice_moves_600_herself_with_her_own_token(self):
        await self.sign_in("alice")
        out = await self.send()
        self.assertEqual((out["word"], out["tone"], out["status"], out["protected"]), ("Answered", "ok", 200, True))
        self.assertEqual((out["title"], out["system"], out["summary"]), ("Alice called transfer_funds", "MCP proxy", "The bank's tool answered."))
        self.assertEqual([(f["label"], f["value"]) for f in out["facts"]][0], ("Asked", "from_account ACC-1001, to_account ACC-2001, amount 600"))
        self.assertIn("status done", out["facts"][1]["value"])
        call = self.world.mcp.log[-1]
        self.assertEqual((call["method"], call["params"]["name"]), ("tools/call", "transfer_funds"))
        self.assertEqual(
            call["params"]["arguments"], {"from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 600}
        )
        claims = bearer_claims(call["authorization"])
        self.assertEqual((claims["username"], claims.get("act")), ("alice@acme-bank.test", None))  # hers, not delegated
        self.assertEqual((out["transaction_id"], out["request_id"], out["api"]), ("tx-mcp-1", "req-mcp-1", "mcp"))     # the gateway's own ids: what the evidence is found by

    async def test_a_denial_shows_the_gateways_message_and_the_request_its_decision_is_filed_under(self):
        await self.sign_in("alice")
        out = await self.send(amount=12000)
        self.assertEqual((out["word"], out["tone"], out["status"]), ("Denied by policy", "deny", 403))
        self.assertEqual(out["summary"], "Denied by policy: Not allowed by ACME authorization policy")
        self.assertEqual(out["request_id"], "req-mcp-1", "the request the denial names is the one its decision is filed under")
        decision = next(e for e in out["evidence"] if e["kind"] == "decisions")
        self.assertIn("request=req-mcp-1", decision["url"])

    async def test_a_teller_does_not_move_customer_money(self):
        await self.sign_in("tina")
        self.assertEqual((await self.send(amount=50))["word"], "Denied by policy")

    async def test_the_amount_goes_on_as_typed_so_the_policies_answer_for_zero_and_negative(self):
        await self.sign_in("alice")
        for amount in (0, -5, 600.5):
            out = await self.send(amount=amount)
            self.assertEqual(self.world.mcp.log[-1]["params"]["arguments"]["amount"], amount)
            self.assertEqual(out["word"], "Answered" if amount > 0 else "Denied by policy", amount)

    async def test_a_reference_is_passed_on_when_there_is_one(self):
        await self.sign_in("alice")
        await self.send(reference="  rent ")
        self.assertEqual(self.world.mcp.log[-1]["params"]["arguments"]["reference"], "rent")

    async def test_without_the_gateway_the_bank_moves_anyones_money_and_says_so(self):
        await self.sign_in("bob")
        out = await self.send(gateway="off")  # Bob, from Alice's account
        self.assertEqual((out["word"], out["protected"], out["title"]), ("Answered", False, "Bob called transfer_funds"))
        self.assertIsNone(self.world.bank.mcp.log[-1]["authorization"])
        self.assertEqual((out["system"], out["direct"], out["request_id"], out["evidence"]), ("No gateway", True, None, []))
        self.assertEqual(self.world.mcp.log, [])

    async def test_a_request_that_is_not_a_transfer_is_refused(self):
        await self.sign_in("alice")
        for fields in (
            {"from_account": ""},
            {"to_account": None},
            {"amount": "600"},
            {"amount": True},
            {"amount": None},
            {"from_account": "A" * 21},
            {"gateway": "maybe"},
        ):
            body = {"from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 1, **fields}
            self.assertEqual((await self.http.post("/api/send-money", json=body)).status_code, 400, fields)
        self.assertEqual(self.world.mcp.log, [])

    async def test_the_log_line_says_who_and_the_outcome_but_not_the_transfer(self):
        await self.sign_in("alice")
        with self.assertLogs("bank-web", level="INFO") as logs:
            await self.send(amount=12000)
        self.assertIn("send-money alice gateway=on Denied by policy", "\n".join(logs.output))
        self.assertIsNone(re.search(r"\b12000\b", "\n".join(logs.output)), "the amount, as a number of its own")
        self.assertNotIn("ACC-", "\n".join(logs.output))


class WhyACallWasRefused(unittest.IsolatedAsyncioTestCase):
    """"No token was sent" is the reason a proxy refused a call that carried none. A payment made without the gateway sends no token by design, so a refusal there
    has another reason, which is the bank's own."""

    async def refused(self, *, gateway: bool, token: str | None, person) -> dict:
        refusal = mcp_rpc.McpReply(401, {"message": "Unauthorized"}, 3, None, None)
        with mock.patch.object(mcp_rpc, "call", mock.AsyncMock(return_value=refusal)):
            return await money.send(None, "http://mcp.test/", token, {"from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 600}, person, gateway=gateway)

    async def test_the_gateway_s_refusal_of_a_call_with_no_token_says_none_was_sent(self):
        out = await self.refused(gateway=True, token=None, person=None)
        self.assertEqual((out["status"], out["summary"]), (401, f"Unauthorized: {hops.NO_TOKEN}"))

    async def test_a_refusal_of_a_call_without_the_gateway_does_not_say_it_though_it_carried_no_token(self):
        out = await self.refused(gateway=False, token=None, person=PERSONAS["alice"])
        self.assertEqual(out["status"], 401)
        self.assertNotIn(hops.NO_TOKEN, out["summary"])

    async def test_a_refusal_of_a_call_with_a_token_says_what_the_proxy_said(self):
        out = await self.refused(gateway=True, token="token", person=PERSONAS["alice"])
        self.assertEqual(out["status"], 401)
        self.assertNotIn(hops.NO_TOKEN, out["summary"])
