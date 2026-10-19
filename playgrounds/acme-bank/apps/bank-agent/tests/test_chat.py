"""The loop: tools from tools/list, the model's calls to the bank, the nudge, the safety nets, the trace."""
import json
import unittest
from unittest import mock

from chat import BROKEN, CALL_AGAIN, EMPTY_ANSWER, GAVE_UP, MAX_TURNS, NO_QUESTION, NUDGE, Ace
from tests.fakes import TOOLS, World, alice_token, completion, tool_call

BALANCE = tool_call("get_balance", account_id="ACC-1001")


def names(rows):
    return [(r["step"], r["name"], r["outcome"]) for r in rows]


class ToolCalling(unittest.IsolatedAsyncioTestCase):
    async def test_a_question_goes_to_the_model_its_tool_call_to_the_bank_and_the_result_back(self):
        world = World(script=[BALANCE, completion("You have 4820.55 EUR on ACC-1001.")])
        async with world.ace() as ace:
            reply = await ace.reply("What is the balance of ACC-1001?", alice_token())
        self.assertEqual(reply.answer, "You have 4820.55 EUR on ACC-1001.")
        first, second = world.llm.asked(0), world.llm.asked(1)
        self.assertEqual((first["model"], first["temperature"], first["reasoning_effort"]), ("acme-chat", 0.2, "none"))
        self.assertEqual([m["role"] for m in first["messages"]], ["system", "user"])
        self.assertIn("Alice Martin (customer id C-1001", first["messages"][0]["content"])      # from the token's claims
        self.assertEqual(first["messages"][1]["content"], "What is the balance of ACC-1001?")
        asked = second["messages"][-2:]                                    # the call, then what the bank answered
        self.assertEqual(json.loads(asked[0]["tool_calls"][0]["function"]["arguments"]), {"account_id": "ACC-1001"})
        self.assertEqual((asked[1]["role"], asked[1]["tool_call_id"]), ("tool", asked[0]["tool_calls"][0]["id"]))
        self.assertEqual(json.loads(asked[1]["content"])["balance"], 4820.55)
        self.assertEqual(world.gateway.tool_calls(), ["get_balance"])

    async def test_the_model_is_not_told_the_users_accounts_when_the_question_names_an_account(self):
        world = World(script=[tool_call("get_balance", account_id="ACC-2001"), completion("That is not allowed."),
                              completion("Hello Alice.")])
        async with world.ace() as ace:
            await ace.reply("What is the balance of ACC-2001?", alice_token())
            await ace.reply("Hello", alice_token())
        named, unnamed = (world.llm.asked(i)["messages"][0]["content"] for i in (0, 2))
        self.assertIn("Alice Martin (customer id C-1001).", named)
        self.assertIn("Alice Martin (customer id C-1001, accounts ACC-1001, ACC-1002).", unnamed)

    async def test_the_trace_has_a_row_for_each_hop_with_the_gateways_ids(self):
        world = World(script=[BALANCE, completion("4820.55 EUR.")])
        async with world.ace() as ace:
            reply = await ace.reply("What is the balance of ACC-1001?", alice_token())
        rows = reply.data["trace"]
        self.assertEqual([r for r in names(rows) if r[0] != "exchange"],
                         [("tool", "tools/list", "ok"), ("llm", "acme-chat", "ok"), ("tool", "get_balance", "ok"),
                          ("llm", "acme-chat", "ok")])
        listing, llm, call = (next(r for r in rows if r["name"] == name)
                              for name in ("tools/list", "acme-chat", "get_balance"))   # the first row of each
        self.assertEqual(listing["detail"], "8 tools")
        self.assertEqual((llm["detail"], llm["status"], llm["transaction_id"]),
                         ("15 tokens, 1 tool call(s)", 200, "llm-1"))
        self.assertEqual(call["arguments"], {"account_id": "ACC-1001"})
        self.assertEqual(call["detail"], '{ "account_id": "ACC-1001", "balance": 4820.55, "currency": "EUR" }')
        self.assertEqual(call["status"], 200)
        self.assertRegex(call["transaction_id"], r"^tx-\d+$")
        self.assertRegex(call["request_id"], r"^req-\d+$")
        self.assertTrue(all(isinstance(r["ms"], int) for r in rows))
        json.dumps(reply.data)                                             # what goes in a data part is plain JSON

    async def test_the_model_is_offered_the_tools_the_user_may_use_and_the_reply_says_which(self):
        world = World(script=[completion("Hello Alice.")])
        async with world.ace(hidden=("freeze_card",)) as ace:
            reply = await ace.reply("Hello", alice_token())
        offered = [t["function"]["name"] for t in world.llm.asked(0)["tools"]]
        self.assertEqual(len(offered), 7)
        self.assertNotIn("freeze_card", offered)
        self.assertEqual(reply.data["tools"], offered)
        self.assertEqual(world.llm.asked(0)["tools"][0]["function"]["parameters"]["required"], ["customer_id"])

    async def test_a_tool_that_says_no_is_an_error_row_and_the_model_explains(self):
        world = World(script=[tool_call("get_balance", account_id="NOPE"), completion("That account does not exist.")])
        async with world.ace() as ace:
            reply = await ace.reply("Balance of NOPE", alice_token())
        row = next(r for r in reply.data["trace"] if r["name"] == "get_balance")
        self.assertEqual(row["outcome"], "error")
        self.assertIn("Unknown account NOPE", row["detail"])
        self.assertIn("Unknown account NOPE", world.llm.asked(1)["messages"][-1]["content"])
        self.assertEqual(reply.answer, "That account does not exist.")

    async def test_a_strict_amount_the_model_got_wrong_is_the_servers_error_not_a_transfer(self):
        world = World(script=[tool_call("transfer_funds", from_account="ACC-1001", to_account="ACC-2001", amount="600"),
                              completion("The amount must be a number.")])
        async with world.ace() as ace:
            reply = await ace.reply("Send 600 EUR from ACC-1001 to ACC-2001", alice_token())
        self.assertEqual(next(r for r in reply.data["trace"] if r["name"] == "transfer_funds")["outcome"], "error")

    async def test_at_most_four_calls_of_the_model(self):
        world = World(script=[BALANCE] * (MAX_TURNS + 1))
        async with world.ace() as ace:
            reply = await ace.reply("balance", alice_token())
        self.assertEqual(reply.answer, GAVE_UP)
        self.assertEqual(len(world.llm.requests), MAX_TURNS)

    async def test_an_empty_question_is_not_sent_anywhere(self):
        world = World()
        async with world.ace() as ace:
            reply = await ace.reply("  ", alice_token())
        self.assertEqual((reply.answer, reply.data["trace"]), (NO_QUESTION, []))
        self.assertEqual((world.llm.requests, world.gateway.requests, world.am.requests), ([], [], []))

    async def test_a_failure_nobody_planned_for_is_a_sentence_and_a_row_not_an_exception(self):
        world = World(script=[completion("never asked")])
        async with world.ace() as ace:
            with mock.patch.object(Ace, "_converse", side_effect=RuntimeError("boom")), \
                    self.assertLogs("bank-agent", "ERROR"):
                reply = await ace.reply("balance", alice_token())
        self.assertEqual(reply.answer, BROKEN)
        self.assertEqual(reply.data["trace"][-1]["outcome"], "error")


class Nudge(unittest.IsolatedAsyncioTestCase):
    """A small model answers "What's my balance?" by asking for an id: asked once more, for such questions only."""

    async def test_a_question_about_money_answered_without_a_tool_is_asked_again_once(self):
        world = World(script=[completion("Which account?"), tool_call("list_accounts", customer_id="C-1001"),
                              completion("EUR 4820.55 on ACC-1001.")])
        async with world.ace() as ace:
            reply = await ace.reply("What's my balance?", alice_token())
        self.assertEqual(reply.answer, "EUR 4820.55 on ACC-1001.")
        retry = world.llm.asked(1)["messages"]
        self.assertEqual([m["role"] for m in retry], ["system", "user", "assistant", "user"])
        self.assertEqual((retry[2]["content"], retry[3]["content"]), ("Which account?", NUDGE))
        self.assertEqual(world.gateway.tool_calls(), ["list_accounts"])

    def test_the_nudge_is_a_plain_request_the_guard_rails_do_not_read_as_an_instruction_to_the_model(self):
        """An order such as "Do not answer without one." can make the guard rails block the nudge turn as an injection,
        and the user then reads "blocked by ACME's AI policy" for a plain question."""
        self.assertNotRegex(NUDGE, r"(?i)\b(?:not|never|ignore|reveal|instructions?)\b")

    async def test_it_is_not_forced_on_a_greeting(self):
        world = World(script=[completion("I am Ace, ACME Bank's assistant.")])
        async with world.ace() as ace:
            reply = await ace.reply("Hello, who are you?", alice_token())
        self.assertEqual(reply.answer, "I am Ace, ACME Bank's assistant.")
        self.assertEqual(len(world.llm.requests), 1)

    async def test_it_is_only_tried_once(self):
        world = World(script=[completion("Which account?"), completion("I still need an account.")])
        async with world.ace() as ace:
            reply = await ace.reply("How much money do I have?", alice_token())
        self.assertEqual(reply.answer, "I still need an account.")
        self.assertEqual(len(world.llm.requests), 2)

    async def test_it_is_not_tried_for_an_answer_that_follows_a_tool_result(self):
        world = World(script=[BALANCE, completion("Your balance is 4820.55 EUR.")])
        async with world.ace() as ace:
            reply = await ace.reply("What is my balance on ACC-1001?", alice_token())
        self.assertEqual(reply.answer, "Your balance is 4820.55 EUR.")
        self.assertEqual(len(world.llm.requests), 2)

    async def test_it_is_not_tried_when_the_user_may_use_no_tool(self):
        world = World(script=[completion("I cannot access your accounts.")])
        async with world.ace(hidden=tuple(t.__name__ for t in TOOLS)) as ace:
            reply = await ace.reply("What's my balance?", alice_token())
        self.assertEqual(reply.answer, "I cannot access your accounts.")
        self.assertNotIn("tools", world.llm.asked(0))                      # an empty list of tools is not sent
        self.assertEqual(len(world.llm.requests), 1)


class SafetyNets(unittest.IsolatedAsyncioTestCase):
    async def test_an_empty_answer_becomes_a_fixed_sentence(self):
        world = World(script=[completion("")])
        async with world.ace() as ace:
            reply = await ace.reply("Freeze CARD-1001, it was stolen", alice_token())
        self.assertEqual(reply.answer, EMPTY_ANSWER)

    async def test_an_empty_answer_after_the_nudge_is_the_same_sentence(self):
        world = World(script=[completion(None), completion("")])
        async with world.ace() as ace:
            reply = await ace.reply("What is my balance?", alice_token())
        self.assertEqual((reply.answer, len(world.llm.requests)), (EMPTY_ANSWER, 2))

    async def test_malformed_arguments_go_back_to_the_model_once_and_never_to_the_bank(self):
        world = World(script=[completion(tool_calls=[{"name": "get_balance", "arguments": '{"account_id": "ACC-10'}]),
                              BALANCE, completion("EUR 4820.55.")])
        async with world.ace() as ace:
            reply = await ace.reply("Balance of ACC-1001", alice_token())
        self.assertEqual(reply.answer, "EUR 4820.55.")
        told = json.loads(world.llm.asked(1)["messages"][-1]["content"])
        self.assertEqual(told["error"], "invalid_arguments")
        self.assertEqual(world.gateway.tool_calls(), ["get_balance"])      # only the well-formed call
        bad = next(r for r in reply.data["trace"] if r["step"] == "tool" and r["outcome"] == "error")
        self.assertEqual((bad["name"], bad["arguments"]), ("get_balance", {}))

    async def test_arguments_that_are_not_an_object_count_as_malformed(self):
        world = World(script=[completion(tool_calls=[{"name": "get_balance", "arguments": '["ACC-1001"]'}]),
                              completion("Sorry.")])
        async with world.ace() as ace:
            reply = await ace.reply("Hi", alice_token())
        self.assertEqual(reply.answer, "Sorry.")
        self.assertEqual(world.gateway.tool_calls(), [])

    async def test_a_second_malformed_call_ends_the_turn(self):
        bad = completion(tool_calls=[{"name": "get_balance", "arguments": "{"}])
        world = World(script=[bad, bad, completion("never reached")])
        async with world.ace() as ace:
            reply = await ace.reply("Balance of ACC-1001", alice_token())
        self.assertEqual(reply.answer, GAVE_UP)
        self.assertEqual((len(world.llm.requests), world.gateway.tool_calls()), (2, []))

    async def test_a_tool_call_written_as_text_is_made_a_real_one(self):
        written = '<tool>{"name": "get_exchange_rate", "arguments": {"base": "EUR", "quote": "USD", "amount": 100}}</tool>'
        world = World(script=[completion(written), completion("100 EUR is 108.00 USD.")])
        async with world.ace() as ace:
            reply = await ace.reply("Convert 100 EUR to USD", alice_token())
        self.assertEqual(reply.answer, "100 EUR is 108.00 USD.")
        self.assertEqual(world.gateway.tool_calls(), ["get_exchange_rate"])
        call = world.llm.asked(1)["messages"][-2]
        self.assertEqual(call["tool_calls"][0]["function"]["name"], "get_exchange_rate")

    async def test_an_exchange_with_an_amount_comes_back_converted_to_the_model(self):
        world = World(script=[tool_call("get_exchange_rate", base="EUR", quote="USD", amount=2500),
                              completion("2500 EUR is 2700.00 USD.")])
        async with world.ace() as ace:
            reply = await ace.reply("How much is 2500 EUR in USD?", alice_token())
        self.assertEqual(json.loads(world.llm.asked(1)["messages"][-1]["content"])["converted"], 2700.0)
        call = next(r for r in reply.data["trace"] if r["name"] == "get_exchange_rate")
        self.assertEqual((call["outcome"], call["arguments"]), ("ok", {"base": "EUR", "quote": "USD", "amount": 2500}))

    async def test_a_missing_argument_is_asked_for_once_as_a_user_turn(self):
        """The validation error alone is answered in words; with the extra turn the model calls the tool again."""
        world = World(script=[tool_call("get_exchange_rate", base="EUR", quote="USD"),
                              tool_call("get_exchange_rate", base="EUR", quote="USD", amount=1),
                              completion("1 EUR is 1.08 USD.")])
        async with world.ace() as ace:
            reply = await ace.reply("What is the euro to dollar rate?", alice_token())
        self.assertEqual(reply.answer, "1 EUR is 1.08 USD.")
        self.assertEqual(world.llm.asked(1)["messages"][-1], {"role": "user", "content": CALL_AGAIN})
        outcomes = [r["outcome"] for r in reply.data["trace"] if r["name"] == "get_exchange_rate"]
        self.assertEqual(outcomes, ["error", "ok"])

    async def test_that_extra_turn_is_not_repeated(self):
        world = World(script=[tool_call("get_exchange_rate", base="EUR", quote="USD"),
                              tool_call("get_exchange_rate", base="EUR", quote="USD"),
                              completion("I need an amount.")])
        async with world.ace() as ace:
            await ace.reply("What is the euro to dollar rate?", alice_token())
        users = [m for m in world.llm.asked(2)["messages"] if m["role"] == "user" and m["content"] == CALL_AGAIN]
        self.assertEqual(len(users), 1)

    async def test_a_tool_that_was_not_offered_is_not_called_even_when_written_as_text(self):
        """A customer asks to freeze a card: the tool is hidden from them, the model writes the call anyway."""
        written = '<tool>\n{"name": "freeze_card", "arguments": {"card_id": "CARD-1001"}}\n</tool>'
        world = World(script=[completion(written)])
        async with world.ace(hidden=("freeze_card",)) as ace:
            reply = await ace.reply("Freeze CARD-1001, it was stolen", alice_token())
        self.assertEqual(reply.answer, EMPTY_ANSWER)                       # never the markup
        self.assertEqual(world.gateway.tool_calls(), [])

    async def test_text_that_only_looks_like_a_tool_call_is_left_alone(self):
        for text in ("<tool>not json</tool>", '<tool>["get_balance"]</tool>'):
            world = World(script=[completion(text)])
            async with world.ace() as ace:
                reply = await ace.reply("Hello", alice_token())
            self.assertEqual((reply.answer, world.gateway.tool_calls()), (text, []), text)

    async def test_a_call_written_as_text_with_arguments_that_are_no_object_is_not_made_real(self):
        written = '<tool>{"name": "get_balance", "arguments": "ACC-1001"}</tool>'
        world = World(script=[completion(f"Let me check. {written}")])
        async with world.ace() as ace:
            reply = await ace.reply("Hello", alice_token())
        self.assertEqual((reply.answer, world.gateway.tool_calls()), ("Let me check.", []))


if __name__ == "__main__":
    unittest.main()
