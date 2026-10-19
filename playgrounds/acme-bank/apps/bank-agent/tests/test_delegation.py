"""Acting for the user: the token exchange at AM, its cache, the switch that turns it off, and what happens when it fails."""
import base64
import json
import unittest
from dataclasses import replace
from unittest import mock

from starlette.responses import JSONResponse, Response

from chat import CANNOT_ACT
from tests.fakes import (AGENT_SECRET, ALICE, BEHIND_THE_GATEWAY, TINA, Unreachable, World, alice_token, claims_of,
                         completion, fake_jwt, tool_call)

BALANCE = tool_call("get_balance", account_id="ACC-1001")
QUESTION = "What is the balance of ACC-1001?"
EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS = "urn:ietf:params:oauth:token-type:access_token"
OWN_TOKEN, EXCHANGE = "client_credentials", "token-exchange"        # what a call to AM asks for: Ace's own token, or an exchange


def row(reply, step):
    return next(r for r in reply.data["trace"] if r["step"] == step)


def sent_to_the_bank(world):
    return {r["authorization"] for r in world.gateway.requests}


class Exchange(unittest.IsolatedAsyncioTestCase):
    async def test_the_users_token_is_exchanged_with_ace_as_the_actor(self):
        world = World(script=[BALANCE, completion("EUR 4820.55.")])
        async with world.ace() as ace:
            await ace.reply(QUESTION, alice_token())
        own, exchange = world.am.requests
        basic = "Basic " + base64.b64encode(f"ace-agent:{AGENT_SECRET}".encode()).decode()
        self.assertEqual(own, {"grant_type": "client_credentials", "authorization": basic})
        self.assertEqual(exchange["authorization"], basic)
        self.assertEqual({k: v for k, v in exchange.items() if k not in ("authorization", "actor_token")},
                         {"grant_type": EXCHANGE_GRANT, "subject_token": alice_token(), "subject_token_type": ACCESS,
                          "actor_token_type": ACCESS, "requested_token_type": ACCESS})
        self.assertEqual(claims_of(exchange["actor_token"])["sub"], "ace-agent")      # Ace's own token

    async def test_the_bank_gets_the_delegated_token_never_the_users(self):
        world = World(script=[BALANCE, completion("EUR 4820.55.")])
        async with world.ace() as ace:
            reply = await ace.reply(QUESTION, alice_token())
        (authorization,) = sent_to_the_bank(world)
        delegated = claims_of(authorization.removeprefix("Bearer "))
        self.assertEqual((delegated["sub"], delegated["act"]["sub"]), ("alice-id", "ace-agent"))
        self.assertEqual(reply.data["delegated_claims"], delegated)               # what the web app shows
        self.assertNotIn(f"Bearer {alice_token()}", sent_to_the_bank(world))

    async def test_the_exchange_is_a_row_of_the_trace_and_the_trace_holds_no_token(self):
        world = World(script=[BALANCE, completion("EUR 4820.55.")])
        async with world.ace() as ace:
            reply = await ace.reply(QUESTION, alice_token())
        exchange = row(reply, "exchange")
        self.assertEqual((exchange["name"], exchange["outcome"], exchange["status"]), ("token-exchange", "ok", 200))
        self.assertEqual(exchange["detail"], "issued: sub = the user, act.sub = ace-agent")
        self.assertEqual(reply.data["trace"][0], exchange)                         # before the tools are listed
        everything = json.dumps(reply.data)
        for secret in (alice_token(), world.gateway.requests[0]["authorization"].removeprefix("Bearer "), AGENT_SECRET,
                       world.am.requests[1]["actor_token"]):
            self.assertNotIn(secret, everything)

    async def test_the_prompt_comes_from_the_users_claims_not_from_the_delegated_token(self):
        world = World(script=[completion("Hello.")])
        async with world.ace() as ace:
            await ace.reply("Hello", alice_token())
        self.assertIn("Alice Martin (customer id C-1001", world.llm.asked(0)["messages"][0]["content"])


class AnActorTokenAmForgot(unittest.IsolatedAsyncioTestCase):
    """Ace keeps its own token for two hours. An AM that refuses it (a domain set up again) must not lock every user out."""

    async def test_ace_asks_for_a_new_token_of_its_own_once_and_goes_on(self):
        world = World(script=[completion("One."), completion("Two.")])
        async with world.ace() as ace:
            first = await ace.reply("Hello", alice_token())
            world.am.forgotten.add(claims_of(world.am.requests[1]["actor_token"])["jti"])
            second = await ace.reply("Hello", fake_jwt(**TINA))
        self.assertEqual(world.am.grants(), [OWN_TOKEN, EXCHANGE, EXCHANGE, OWN_TOKEN, EXCHANGE])
        self.assertEqual((row(first, "exchange")["outcome"], row(second, "exchange")["outcome"]), ("ok", "ok"))
        self.assertEqual(row(second, "exchange")["detail"].split(":")[0], "issued")

    async def test_a_token_that_was_just_issued_and_is_refused_is_not_asked_for_again(self):
        world = World(script=[completion("No.")])
        world.am.failure = JSONResponse({"error": "invalid_request", "error_description": "The presented token is invalid"}, 400)
        async with world.ace() as ace:
            reply = await ace.reply("Hello", alice_token())
        self.assertEqual(reply.answer, CANNOT_ACT)
        self.assertEqual(world.am.grants(), [OWN_TOKEN])      # AM refused Ace's own token: nothing to retry with

    async def test_a_user_token_that_AM_refuses_is_tried_with_a_new_actor_token_at_most_once(self):
        world = World(script=[completion("One."), completion("No.")])
        async with world.ace() as ace:
            await ace.reply("Hello", alice_token())
            world.am.failure = JSONResponse({"error": "invalid_request", "error_description": "The presented token is invalid"}, 400)
            reply = await ace.reply("Hello", fake_jwt(**TINA))
        self.assertEqual(reply.answer, CANNOT_ACT)
        self.assertEqual(world.am.grants(), [OWN_TOKEN, EXCHANGE, EXCHANGE, OWN_TOKEN])


class AnAmThatIsNotAvailable(unittest.IsolatedAsyncioTestCase):
    """Only a token AM says it does not accept (400, 401) is replaced and asked for again. An AM that is busy or down is not a
    reason to ask it twice: Ace keeps its token and the user is told, as for any other refusal."""

    async def refused_with(self, status: int):
        world = World(script=[completion("One."), completion("No.")])
        async with world.ace() as ace:
            await ace.reply("Hello", alice_token())                  # Ace holds its own token and a delegation in its cache
            world.am.failure = JSONResponse({"error": "temporarily_unavailable"}, status)
            reply = await ace.reply("Hello", fake_jwt(**TINA))       # another user: an exchange to make
        return world, reply

    async def test_a_503_is_not_retried_with_a_new_token_of_ace(self):
        world, reply = await self.refused_with(503)
        self.assertEqual(reply.answer, CANNOT_ACT)
        self.assertEqual(world.am.grants(), [OWN_TOKEN, EXCHANGE, EXCHANGE])        # one exchange that failed, no second token, no second exchange

    async def test_neither_is_any_other_answer_that_is_not_a_refusal_of_the_token(self):
        for status in (500, 502, 504, 429, 403):
            world, reply = await self.refused_with(status)
            self.assertEqual(world.am.grants(), [OWN_TOKEN, EXCHANGE, EXCHANGE], status)
            self.assertEqual(reply.answer, CANNOT_ACT, status)

    async def test_a_400_still_is(self):
        world, reply = await self.refused_with(400)
        self.assertEqual(world.am.grants(), [OWN_TOKEN, EXCHANGE, EXCHANGE, OWN_TOKEN])


class Cache(unittest.IsolatedAsyncioTestCase):
    async def test_a_second_chat_of_the_same_user_does_not_ask_AM_again(self):
        world = World(script=[completion("One."), completion("Two.")])
        async with world.ace() as ace:
            first = await ace.reply("Hello", alice_token())
            second = await ace.reply("Hello again", alice_token())
        self.assertEqual(world.am.grants(), [OWN_TOKEN, EXCHANGE])
        self.assertEqual(row(first, "exchange")["detail"].split(":")[0], "issued")
        self.assertEqual(row(second, "exchange")["detail"].split(":")[0], "reused")
        self.assertEqual(len(sent_to_the_bank(world)), 1)                           # the same token both times

    async def test_another_user_has_their_own_token_but_Ace_keeps_hers(self):
        world = World(script=[completion("One."), completion("Two.")])
        async with world.ace() as ace:
            await ace.reply("Hello", alice_token())
            await ace.reply("Hello", fake_jwt(**TINA))
        self.assertEqual(world.am.grants(), [OWN_TOKEN, EXCHANGE, EXCHANGE])
        self.assertEqual(len(sent_to_the_bank(world)), 2)

    async def test_a_new_token_of_the_same_user_is_a_new_exchange(self):
        world = World(script=[completion("One."), completion("Two.")])
        async with world.ace() as ace:
            await ace.reply("Hello", fake_jwt(**ALICE, jti="first"))
            await ace.reply("Hello", fake_jwt(**ALICE, jti="refreshed"))
        self.assertEqual(world.am.grants(), [OWN_TOKEN, EXCHANGE, EXCHANGE])

    async def test_tokens_are_replaced_before_they_expire(self):
        world = World(script=[completion("One."), completion("Two."), completion("Three.")])
        world.am.lifetime = 100                                                      # 70 s of use, 30 s of margin
        with mock.patch("identity.time") as clock:
            clock.monotonic.return_value = 1000.0
            async with world.ace() as ace:
                await ace.reply("Hello", alice_token())
                clock.monotonic.return_value = 1069.0
                await ace.reply("Hello", alice_token())                              # still good
                clock.monotonic.return_value = 1071.0
                await ace.reply("Hello", alice_token())                              # both tokens are replaced
        self.assertEqual(world.am.grants(), [OWN_TOKEN, EXCHANGE, OWN_TOKEN, EXCHANGE])

    async def test_the_cache_does_not_grow_without_end(self):
        world = World(script=[completion("ok")] * 3)
        async with world.ace() as ace:
            with mock.patch("identity.CACHE_LIMIT", 2):
                for jti in ("a", "b", "c"):
                    await ace.reply("Hello", fake_jwt(**ALICE, jti=jti))
            self.assertEqual(len(ace.delegation.cache), 2)
            self.assertNotIn(fake_jwt(**ALICE, jti="a"), ace.delegation.cache)      # the oldest went


class Switch(unittest.IsolatedAsyncioTestCase):
    async def test_with_delegation_off_the_users_token_goes_to_the_bank_and_AM_is_not_called(self):
        world = World(replace(BEHIND_THE_GATEWAY, delegation=False), [BALANCE, completion("EUR 4820.55.")])
        async with world.ace() as ace:
            reply = await ace.reply(QUESTION, alice_token())
        self.assertEqual(sent_to_the_bank(world), {f"Bearer {alice_token()}"})
        self.assertEqual(world.am.requests, [])
        self.assertNotIn("exchange", [r["step"] for r in reply.data["trace"]])
        self.assertNotIn("delegated_claims", reply.data)
        self.assertEqual(reply.answer, "EUR 4820.55.")


class Failure(unittest.IsolatedAsyncioTestCase):
    """Without the delegated token Ace does not act: the user's own token would lift the agent's limits at the bank."""

    async def chat_with(self, world, **ace_options):
        async with world.ace(**ace_options) as ace:
            return await ace.reply(QUESTION, alice_token())

    def assert_refused(self, world, reply, detail, status=None):
        exchange = row(reply, "exchange")
        self.assertEqual((exchange["outcome"], exchange.get("status")), ("error", status))
        self.assertEqual(exchange["detail"], f"{detail}. No tool was called.")
        self.assertEqual(reply.answer, CANNOT_ACT)
        self.assertEqual([r["step"] for r in reply.data["trace"]], ["exchange"])
        self.assertEqual(world.gateway.requests, [])           # not a hop to the bank, not even tools/list
        self.assertEqual(world.llm.requests, [])
        self.assertEqual(reply.data["tools"], [])
        self.assertNotIn("delegated_claims", reply.data)

    async def test_AM_refuses_the_exchange(self):
        world = World(script=[BALANCE, completion("EUR 4820.55.")])
        world.am.failure = JSONResponse({"error": "invalid_grant",
                                         "error_description": "Token exchange is not allowed"}, 400)
        reply = await self.chat_with(world)
        self.assert_refused(world, reply, "AM answered 400: Token exchange is not allowed", 400)

    async def test_AM_does_not_know_Ace(self):
        world = World(replace(BEHIND_THE_GATEWAY, agent_client_secret="wrong"), [BALANCE, completion("EUR 4820.55.")])
        reply = await self.chat_with(world)
        self.assert_refused(world, reply, "AM answered 401: Bad client credentials", 401)

    async def test_AM_is_down(self):
        world = World(script=[BALANCE, completion("EUR 4820.55.")])
        reply = await self.chat_with(world, am_transport=Unreachable())
        self.assert_refused(world, reply, "AM did not answer (ConnectError)")

    async def test_AM_answers_something_else_than_a_token(self):
        world = World(script=[BALANCE, completion("EUR 4820.55.")])
        for body in ("<html>maintenance</html>", json.dumps({"token_type": "bearer"}), "[]"):
            world.am.failure = Response(body, 200)
            reply = await self.chat_with(world)
            self.assert_refused(world, reply, "AM answered without a token", 200)

    async def test_a_token_that_does_not_say_the_user_through_Ace_is_not_used(self):
        """A token without `act` is the user's own as far as the bank can tell: the agent's cap would not apply."""
        cases = [({"act": None}, "AM issued a token that does not name Ace as the actor"),
                 ({"act": {"sub": "another-agent"}}, "AM issued a token that does not name Ace as the actor"),
                 ({"act": "ace-agent"}, "AM issued a token that does not name Ace as the actor"),
                 ({"sub": "bob-id"}, "AM issued a token for someone other than the user"),
                 ({"sub": None}, "AM issued a token for someone other than the user")]
        for claims, detail in cases:
            with self.subTest(claims=claims):
                world = World(script=[BALANCE, completion("EUR 4820.55.")])
                world.am.exchange_claims = claims
                reply = await self.chat_with(world)
                self.assert_refused(world, reply, detail)

    async def test_a_delegated_token_is_not_matched_with_a_user_token_that_has_no_subject(self):
        world = World(script=[BALANCE, completion("EUR 4820.55.")])
        world.am.exchange_claims = {"sub": "someone"}
        async with world.ace() as ace:
            reply = await ace.reply(QUESTION, fake_jwt(name="Alice Martin"))
        self.assert_refused(world, reply, "AM issued a token for someone other than the user")

    async def test_the_failure_is_not_cached(self):
        world = World(script=[completion("One."), completion("Two.")])
        world.am.failure = JSONResponse({"error": "server_error"}, 500)
        async with world.ace() as ace:
            first = await ace.reply("Hello", alice_token())
            world.am.failure = None
            second = await ace.reply("Hello", alice_token())
        self.assertEqual(first.answer, CANNOT_ACT)
        self.assertEqual((row(second, "exchange")["outcome"], second.answer), ("ok", "One."))

    async def test_a_refused_token_is_not_cached_either(self):
        world = World(script=[completion("One.")])
        async with world.ace() as ace:
            world.am.exchange_claims = {"act": None}
            await ace.reply("Hello", alice_token())
            self.assertEqual(ace.delegation.cache, {})
            world.am.exchange_claims = {}
            second = await ace.reply("Hello", alice_token())
        self.assertEqual(row(second, "exchange")["detail"].split(":")[0], "issued")

    async def test_no_user_token_means_nothing_to_exchange(self):
        world = World()
        async with world.ace() as ace:
            reply = await ace.reply("Hello", None)
        self.assertEqual(world.am.requests, [])
        self.assertNotIn("exchange", [r["step"] for r in reply.data["trace"]])


if __name__ == "__main__":
    unittest.main()
