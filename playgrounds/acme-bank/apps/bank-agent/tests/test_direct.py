"""The same image as the direct Ace (bank-agent-direct): no gateway, no identity, no key, a model reached on its own."""
import unittest
from dataclasses import replace

from tests.fakes import BOB, DIRECT, World, alice_token, completion, fake_jwt, tool_call

LIST_ACCOUNTS = tool_call("list_accounts", customer_id="C-1001")


class DirectAce(unittest.IsolatedAsyncioTestCase):
    async def test_it_answers_without_a_key_a_token_or_AM(self):
        world = World(DIRECT, [LIST_ACCOUNTS, completion("EUR 4820.55 on ACC-1001.")])
        async with world.ace(open=True) as ace:
            reply = await ace.reply("Show the accounts of customer C-1001", None)
        self.assertEqual(reply.answer, "EUR 4820.55 on ACC-1001.")
        self.assertEqual(world.gateway.tool_calls(), ["list_accounts"])
        self.assertEqual({r["authorization"] for r in world.gateway.requests}, {""})      # nothing to the bank
        self.assertEqual(world.am.requests, [])
        self.assertEqual([r["step"] for r in reply.data["trace"]], ["tool", "llm", "tool", "llm"])
        self.assertNotIn("delegated_claims", reply.data)

    async def test_the_model_is_called_by_its_own_name_with_its_thinking_off(self):
        world = World(DIRECT, [completion("Hello.")])
        async with world.ace(open=True) as ace:
            await ace.reply("Hello", None)
        asked = world.llm.asked(0)
        self.assertEqual((asked["model"], asked["reasoning_effort"]), ("qwen3:1.7b", "none"))
        headers = world.llm.requests[0]["headers"]
        self.assertNotIn("x-gravitee-api-key", headers)                     # there is no gateway to read it
        self.assertEqual(headers["authorization"], "Bearer none")           # the SDK wants a key: Ollama ignores this one

    async def test_a_model_that_takes_no_reasoning_effort_is_not_asked_for_one(self):
        world = World(replace(DIRECT, llm_reasoning_effort=""), [completion("Hello.")])
        async with world.ace(open=True) as ace:
            await ace.reply("Hello", None)
        self.assertNotIn("reasoning_effort", world.llm.asked(0))

    async def test_the_users_token_still_tells_it_who_is_asking(self):
        """bank-web sends the signed-in user's token to this Ace too: it names the user in the prompt and is not exchanged."""
        world = World(DIRECT, [completion("Hello Alice.")])
        async with world.ace(open=True) as ace:
            reply = await ace.reply("Hello", alice_token())
        self.assertIn("Alice Martin (customer id C-1001", world.llm.asked(0)["messages"][0]["content"])
        self.assertEqual(world.am.requests, [])
        self.assertNotIn("exchange", [r["step"] for r in reply.data["trace"]])

    async def test_what_the_model_asks_for_goes_to_the_bank_whoever_is_asking(self):
        """The lesson of the direct Ace: Bob's question, Alice's accounts, and no policy anywhere to say no."""
        world = World(DIRECT, [LIST_ACCOUNTS, completion("Alice has EUR 4820.55.")])
        async with world.ace(open=True) as ace:
            reply = await ace.reply("Show the accounts of customer C-1001", fake_jwt(**BOB))
        self.assertEqual(reply.answer, "Alice has EUR 4820.55.")
        self.assertEqual(next(r for r in reply.data["trace"] if r["name"] == "list_accounts")["outcome"], "ok")


if __name__ == "__main__":
    unittest.main()
