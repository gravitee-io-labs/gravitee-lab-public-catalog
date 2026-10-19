"""Every scenario of the table against the fake platform: the outcome it expects, what it does when the platform
or the model does not behave, and what it leaves behind."""
import os
import unittest
from unittest import mock

from checks import FAILED, INCONCLUSIVE, OK, SKIPPED
from readiness import A2A, LLM, MCP, WORKSPACE
from runner import Pace
from scenarios import table
from tests import fakes
from tests.fakes import generator, llm_row


def hop(step, name, outcome, status, detail):
    return {"step": step, "name": name, "outcome": outcome, "detail": detail, "ms": 5, "status": status}


# What Ace's trace says when it could not reach something it needs: the platform is at fault, whatever the model did
BROKEN_HOPS = {
    "the key of Ace is refused by the LLM plan": [hop("llm", "acme-chat", "error", 401, "Unauthorized")],
    "the LLM API of Ace is not deployed": [hop("llm", "acme-chat", "error", 404, "No context-path matches")],
    "Ace has no connection to the LLM proxy": [hop("llm", "acme-chat", "error", None, "APIConnectionError")],
    "AM refused the token exchange": [hop("exchange", "token-exchange", "error", 401, "AM answered 401"),
                                      llm_row()],
    "the MCP proxy did not open the session": [hop("tool", "connect", "error", 401, "Sign in again.")],
    "the MCP proxy refused the session": [hop("tool", "connect", "denied", 403, "Not allowed")],
}


def named(runner, name):
    return next(s for s in runner.scenarios if s.name == name)


async def run(runner, name):
    result = await runner.run_one(named(runner, name))
    await runner.world.transfers.settle()
    return result


class TheTable(unittest.IsolatedAsyncioTestCase):
    def test_names_are_unique_and_every_scenario_needs_something_the_platform_has(self):
        scenarios = table()
        self.assertEqual(len({s.name for s in scenarios}), len(scenarios))
        self.assertTrue(all(s.weight > 0 and s.needs <= {LLM, MCP, A2A, WORKSPACE} for s in scenarios))

    def test_the_cards_of_the_story_are_never_named(self):
        for module in ("scenarios.py", "checks.py", "transfers.py", "cast.py"):
            with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), module)) as source:
                text = source.read()
            self.assertNotIn("CARD-1001", text, module)
            self.assertNotIn("CARD-2001", text, module)

    def test_only_the_chats_with_ace_ask_for_tokens_of_its_plan(self):
        for s in table():
            asks_ace = {A2A, MCP, LLM} <= s.needs and s.name != "injection-through-ace"
            self.assertEqual("ace" in s.estimate, asks_ace, s.name)

    async def test_every_scenario_meets_what_it_expects_when_the_platform_behaves(self):
        async with generator() as (platform, runner, clock):
            for scenario in table():
                result = await run(runner, scenario.name)
                self.assertEqual((scenario.name, result.status, result.detail.split(":")[0]),
                                 (scenario.name, OK, result.detail.split(":")[0]), result)

    async def test_the_exchange_rate_is_asked_for_an_amount_so_that_the_bank_converts_it(self):
        async with generator() as (platform, runner, clock):
            await run(runner, "public-tools")
        self.assertIn(("alice", "get_exchange_rate", {"base": "EUR", "quote": "USD", "amount": 2500}),
                      platform.tool_calls)

    async def test_the_story_is_where_the_guide_left_it(self):
        async with generator() as (platform, runner, clock):
            for scenario in table():
                await run(runner, scenario.name)
            balances = platform.bank.balances
            self.assertEqual((balances["ACC-1001"], balances["ACC-1002"], balances["ACC-2001"]),
                             (4820.55, 15300.0, 920.10))
            self.assertEqual((platform.bank.cards["CARD-1001"], platform.bank.cards["CARD-2001"]), ("ACTIVE", "ACTIVE"))
            self.assertEqual(platform.bank.cards["CARD-9001"], "FROZEN")      # the card made for the generator

    async def test_every_scenario_names_who_it_is(self):
        async with generator() as (platform, runner, clock):
            for scenario in table():
                await run(runner, scenario.name)
            self.assertEqual({call["agent"] for call in platform.calls}, {"acme-bank-traffic"})

    async def test_team_hackathon_is_never_touched(self):
        async with generator() as (platform, runner, clock):
            for scenario in table():
                await run(runner, scenario.name)
            every_call = " ".join(f"{c['path']}?{c['query']} {c['headers'].get('authorization')}"
                                  for c in platform.calls)
            self.assertNotIn("hackathon", every_call)
            self.assertEqual(platform.spent["team-hackathon"], 0)

    async def test_a_chat_costs_what_its_trace_says(self):
        async with generator() as (platform, runner, clock):
            result = await run(runner, "alice-accounts")
            self.assertEqual(result.tokens, 1600)                          # 900 + 700 in the fake's two model calls
            self.assertEqual(runner.world.ledger.used("ace"), 1600)

    async def test_an_answer_from_the_cache_says_so_and_costs_nothing(self):
        async with generator(seed=3) as (platform, runner, clock):
            platform.answer_tokens = (30, 40)
            results = [await run(runner, "faq-on-the-traffic-key") for _ in range(12)]     # 6 questions, drawn at random
            self.assertIn("answered from the cache", [r.detail for r in results])
            self.assertEqual(runner.world.ledger.used("traffic"), 70 * sum(1 for r in results if not r.detail))


class WhenThePoliciesAreWrong(unittest.IsolatedAsyncioTestCase):
    async def test_a_denial_that_became_a_permit_is_what_a_switched_off_policy_engine_does_and_the_money_comes_back(self):
        with mock.patch.object(fakes, "permitted", lambda *args, **kwargs: True):
            async with generator() as (platform, runner, clock):
                before = dict(platform.bank.balances)
                for name in ("bob-reads-alices-accounts", "alice-reads-bobs-accounts", "bob-lists-alices-accounts",
                             "tina-sends-nothing", "alice-freezes-nothing", "alice-sends-12000", "alice-sends-zero-and-less",
                             "alice-hides-bobs-account-behind-her-own", "alice-sends-600-through-ace"):
                    result = await run(runner, name)
                    self.assertIn(result.status, (OK, INCONCLUSIVE), name)
                await runner.world.transfers.settle()
                self.assertEqual(platform.bank.balances, before)

    async def test_a_permit_that_became_a_denial_is_a_failure(self):
        with mock.patch.object(fakes, "permitted", lambda *args, **kwargs: False):
            async with generator() as (platform, runner, clock):
                for name in ("alice-accounts", "tina-reads-alices-accounts", "alice-reads-her-accounts",
                             "public-tools"):
                    result = await run(runner, name)
                    self.assertEqual(result.status, FAILED, name)
                    self.assertIn("expected it permitted", result.detail)

    async def test_the_cap_on_agents_that_is_not_there_moves_money_that_comes_back(self):
        def no_cap_for_agents(who, tool, args, via_agent=False):
            return real(who, tool, args, via_agent=False)
        real = fakes.permitted
        with mock.patch.object(fakes, "permitted", no_cap_for_agents):
            async with generator() as (platform, runner, clock):
                result = await runner.run_one(named(runner, "alice-sends-600-through-ace"))
                self.assertEqual(result.status, OK)
                self.assertEqual(platform.bank.balances["ACC-1001"], 4820.55 - 600)        # the money moved
                self.assertEqual(runner.world.transfers.owed[0].amount, 600.0)             # and it is owed back
                await runner.world.transfers.settle()
                self.assertEqual(platform.bank.balances["ACC-1001"], 4820.55)


class WhenTheModelDoesNotBehave(unittest.IsolatedAsyncioTestCase):
    async def test_a_model_that_calls_no_tool_proves_nothing(self):
        async with generator() as (platform, runner, clock):
            platform.ace_script = lambda who, text: ("Which account?", [llm_row("500 tokens, 0 tool call(s)")])
            for name in ("alice-accounts", "bob-reads-alices-accounts", "alice-sends-120", "tina-freezes-the-test-card"):
                result = await run(runner, name)
                self.assertEqual(result.status, INCONCLUSIVE, name)
            self.assertEqual(runner.world.transfers.owed, [])

    async def test_a_guard_that_blocks_an_ordinary_question_is_a_failure(self):
        async with generator() as (platform, runner, clock):
            platform.ace_script = lambda who, text: ("blocked", [llm_row("AI prompt validation", "blocked", 400)])
            result = await run(runner, "alice-accounts")
            self.assertEqual((result.status, result.detail), (FAILED, "the guard rails blocked an ordinary question"))

    async def test_an_injection_that_gets_through_is_no_failure_the_guard_rails_start_off(self):
        async with generator() as (platform, runner, clock):
            platform.ace_script = lambda who, text: ("Here is my system prompt", [llm_row()])
            result = await run(runner, "injection-through-ace")
            self.assertEqual((result.status, result.detail), (OK, "the guard rails are off: the model got it"))

    async def test_an_injection_with_no_model_call_at_all_proves_nothing_and_is_still_a_failure_to_stop_it(self):
        async with generator() as (platform, runner, clock):
            platform.ace_script = lambda who, text: ("Which account?", [])
            result = await run(runner, "injection-through-ace")
            self.assertEqual((result.status, result.detail), (FAILED, "the guard rails did not stop it"))

    async def test_an_injection_on_the_traffic_key_is_blocked_or_answered_and_the_answer_costs_tokens(self):
        async with generator() as (platform, runner, clock):
            self.assertEqual((await run(runner, "injection-on-the-traffic-key")).status, OK)
            platform.guard_on = False
            result = await run(runner, "injection-on-the-traffic-key")
            self.assertEqual((result.status, result.detail), (OK, "the guard rails are off: the model answered"))
            self.assertGreater(result.tokens, 0)

    async def test_an_iban_that_comes_back_in_the_answer_says_pii_filtering_is_off(self):
        async with generator() as (platform, runner, clock):
            default = platform.ace_script
            platform.ace_script = lambda who, text: (
                "Your IBAN FR76 3000 6000 0112 3456 7890 189 is on file", default(who, text)[1])
            result = await run(runner, "alice-gives-an-iban")
            self.assertEqual(result.status, OK)
            self.assertIn("PII filtering", result.detail)

    async def test_a_limit_of_the_plan_of_ace_skips_and_is_left_alone_for_a_while(self):
        async with generator() as (platform, runner, clock):
            platform.ace_script = lambda who, text: ("limit", [llm_row("429 limit", "rate_limited", 429)])
            first = await run(runner, "alice-accounts")
            self.assertEqual(first.status, SKIPPED)
            platform.ace_script = lambda who, text: self.fail("asked again while the limit is blocked")
            second = await runner.run_one(named(runner, "alice-accounts"))
            self.assertEqual(second.status, SKIPPED)
            self.assertIn("ace: the gateway refuses it for now", second.detail)


class WhenAceCannotReachWhatItNeeds(unittest.IsolatedAsyncioTestCase):
    """A chat judges the tool Ace called. When Ace could not reach its model, its sign-in or the bank's tools there is
    no tool to judge, and that must not read as a model that chose not to call one."""

    async def test_every_chat_is_a_failure_that_says_what_broke(self):
        chats = [scenario.name for scenario in table() if {A2A, MCP, LLM} <= scenario.needs]
        self.assertGreaterEqual(len(chats), 11)
        async with generator() as (platform, runner, clock):
            for label, rows in BROKEN_HOPS.items():
                platform.ace_script = lambda who, text, rows=rows: ("Something went wrong", rows)
                for name in chats:
                    result = await run(runner, name)
                    self.assertEqual((label, name, result.status), (label, name, FAILED))
                    self.assertTrue(result.detail.startswith("Ace's "), (label, name, result.detail))

    async def test_the_detail_is_the_one_of_the_hop_and_the_chat_counts_as_trouble(self):
        async with generator() as (platform, runner, clock):
            platform.ace_script = lambda who, text: ("Your session has expired.", [
                hop("tool", "connect", "error", 401, "Your session has expired. Sign in again.")])
            result = await run(runner, "alice-accounts")
            self.assertEqual((result.status, result.detail), (
                FAILED, "Ace's tool connect failed (HTTP 401): Your session has expired. Sign in again."))
            self.assertEqual(runner._trouble["alice-accounts"], 1)

    async def test_three_in_a_row_put_the_features_of_a_chat_back_on_the_waiting_list(self):
        async with generator() as (platform, runner, clock):
            await runner.readiness.check()
            self.assertEqual(runner.readiness.waiting, {})
            platform.ace_script = lambda who, text: ("Sorry", [hop("llm", "acme-chat", "error", 401, "Unauthorized")])
            for _ in range(3):
                await run(runner, "alice-accounts")
            self.assertEqual(set(runner.readiness.waiting), {A2A, MCP, LLM})

    async def test_an_injection_is_not_a_guard_that_failed_when_ace_could_not_reach_its_model(self):
        async with generator() as (platform, runner, clock):
            platform.ace_script = lambda who, text: ("Sorry", [hop("llm", "acme-chat", "error", 401, "Unauthorized")])
            result = await run(runner, "injection-through-ace")
            self.assertEqual((result.status, result.detail), (FAILED, "Ace's llm acme-chat failed (HTTP 401): "
                                                                      "Unauthorized"))

    async def test_a_transfer_that_went_through_before_a_hop_failed_is_still_given_back(self):
        async with generator() as (platform, runner, clock):
            default = platform.ace_script

            def ace(who, text):
                answer, trace = default(who, text)
                return answer, trace + [hop("llm", "acme-chat", "error", None, "APIConnectionError")]
            platform.ace_script = ace
            result = await run(runner, "alice-sends-120")
            self.assertEqual(result.status, FAILED)
            self.assertEqual((runner.world.transfers.moved, runner.world.transfers.returned), (120.0, 120.0))
            self.assertEqual(platform.bank.balances["ACC-1001"], 4820.55)

    async def test_a_session_the_mcp_proxy_limited_is_a_skip_not_a_verdict(self):
        async with generator() as (platform, runner, clock):
            platform.ace_script = lambda who, text: ("Try again", [
                hop("tool", "connect", "rate_limited", 429, "Rate limit exceeded")])
            for name in ("alice-accounts", "bob-reads-alices-accounts", "injection-through-ace"):
                result = await run(runner, name)
                self.assertEqual((result.status, result.detail), (
                    SKIPPED, "Ace's session with the bank's tools was limited: Rate limit exceeded"), name)
            self.assertEqual(runner._trouble["alice-accounts"], 0)
            self.assertEqual(runner.world.ledger.used("ace"), 0)
            self.assertEqual(runner.world.ledger.refusal({"ace": 1}), None)          # the plan of Ace is not blamed


class WhenTheGatewayIsSlow(unittest.IsolatedAsyncioTestCase):
    async def test_a_tool_call_that_takes_too_long_is_cut_cleanly(self):
        async with generator(pace=Pace(timeout=0.2)) as (platform, runner, clock):
            platform.mcp_delay = 5
            with self.assertLogs("bank-traffic", "WARNING") as logs:
                result = await run(runner, "alice-reads-her-accounts")
            self.assertEqual((result.status, result.detail), (FAILED, "no answer in time"))
            self.assertEqual(runner._trouble["alice-reads-her-accounts"], 1)
            platform.mcp_delay = 0
            self.assertEqual((await run(runner, "alice-reads-her-accounts")).status, OK)      # nothing was left broken
            self.assertEqual(len(logs.output), 1)


class WhenAPersonIsRateLimited(unittest.IsolatedAsyncioTestCase):
    """The MCP proxy allows 30 tool calls a minute to each person: a burst of the warm-up can meet it, and that is not
    a verdict."""

    async def test_a_direct_call_that_is_limited_is_a_skip_and_the_calls_after_it_are_not_made(self):
        async with generator() as (platform, runner, clock):
            platform.mcp_limited = True
            result = await run(runner, "alice-reads-her-accounts")
            self.assertEqual(result.status, SKIPPED)
            self.assertIn("alice list_accounts was limited: Rate limit exceeded", result.detail)
            posts = [c for c in platform.seen("/acme-bank/mcp") if c["method"] == "POST"]
            self.assertEqual(len(posts), 2)                                            # discover, then the first call

    async def test_a_chat_whose_tool_call_was_limited_is_a_skip(self):
        async with generator() as (platform, runner, clock):
            row = {"step": "tool", "name": "list_accounts", "arguments": {"customer_id": "C-1001"},
                   "outcome": "rate_limited", "detail": "Rate limit exceeded", "status": 429}
            platform.ace_script = lambda who, text: ("Try again later", [llm_row(), row])
            result = await run(runner, "alice-accounts")
            self.assertEqual((result.status, result.detail), (SKIPPED, "list_accounts was limited: Rate limit exceeded"))

    async def test_a_transfer_that_cannot_be_given_back_because_of_the_limit_stays_owed(self):
        async with generator() as (platform, runner, clock):
            await runner.run_one(named(runner, "alice-sends-120"))
            platform.mcp_limited = True
            with self.assertLogs("bank-traffic", "WARNING"):
                await runner.world.transfers.settle()
            self.assertEqual(len(runner.world.transfers.owed), 1)
            platform.mcp_limited = False
            await runner.world.transfers.settle()
            self.assertEqual(platform.bank.balances["ACC-1001"], 4820.55)


class WhenTheMoneyDoesNotComeBack(unittest.IsolatedAsyncioTestCase):
    async def test_a_transfer_that_cannot_be_given_back_is_tried_again_and_blocks_new_ones(self):
        def bob_cannot_move_money(who, tool, args, via_agent=False):
            return False if (who, tool) == ("bob", "transfer_funds") else real(who, tool, args, via_agent)
        real = fakes.permitted
        async with generator() as (platform, runner, clock):
            await runner.readiness.check()
            with mock.patch.object(fakes, "permitted", bob_cannot_move_money):
                with self.assertLogs("bank-traffic", "WARNING") as logs:
                    result = await run(runner, "alice-sends-120")
                self.assertEqual(result.status, OK)
                self.assertEqual(platform.bank.balances["ACC-1001"], 4820.55 - 120)
                self.assertEqual(len(runner.world.transfers.owed), 1)
                self.assertIn("transfer of 120 EUR back to ACC-1001 is still owed: denied", logs.output[0])
                self.assertFalse(runner._allowed(named(runner, "alice-sends-120")))      # nothing new moves
                self.assertFalse(runner._allowed(named(runner, "alice-sends-600-herself")))
                self.assertTrue(runner._allowed(named(runner, "alice-accounts")))        # the rest goes on
            await runner.world.transfers.settle()                                         # the policies are right again
            self.assertEqual(runner.world.transfers.owed, [])
            self.assertEqual(platform.bank.balances["ACC-1001"], 4820.55)
            self.assertTrue(runner._allowed(named(runner, "alice-sends-120")))

    async def test_an_amount_that_is_a_float_goes_back_as_it_came(self):
        async with generator() as (platform, runner, clock):
            runner.world.transfers.note("ACC-1001", "ACC-2001", 120.0)
            await runner.world.transfers.settle()
            self.assertEqual(platform.bank.balances["ACC-2001"], 920.10 - 120)

    async def test_an_account_nobody_of_the_cast_owns_cannot_be_given_back(self):
        async with generator() as (platform, runner, clock):
            runner.world.transfers.note("ACC-1001", "ACC-9001", 10)
            with self.assertLogs("bank-traffic", "WARNING") as logs:
                await runner.world.transfers.settle()
            self.assertIn("nobody of the cast owns ACC-9001", logs.output[0])
            self.assertEqual(runner.world.transfers.owed, [])

    async def test_the_totals_say_what_moved_and_what_came_back(self):
        async with generator() as (platform, runner, clock):
            await run(runner, "alice-sends-120")
            await run(runner, "alice-sends-600-herself")
            self.assertEqual(runner.world.transfers.status(),
                             {"moved_eur": 720.0, "returned_eur": 720.0, "owed": [], "unexplained": []})


class WhenThePlatformDoesNotAnswer(unittest.IsolatedAsyncioTestCase):
    async def test_a_gateway_that_is_down_fails_the_scenario_with_the_reason(self):
        async with generator() as (platform, runner, clock):
            platform.down = True
            for name in ("alice-accounts", "alice-reads-her-accounts", "faq-on-the-traffic-key"):
                result = await run(runner, name)
                self.assertEqual(result.status, FAILED, name)
                self.assertIn("503", result.detail)

    async def test_an_injection_to_a_gateway_that_is_down_is_not_a_guard_that_failed(self):
        async with generator() as (platform, runner, clock):
            platform.down = True
            result = await run(runner, "injection-on-the-traffic-key")
            self.assertEqual(result.status, FAILED)
            self.assertIn("HTTP 503", result.detail)
            self.assertEqual(runner._trouble["injection-on-the-traffic-key"], 1)       # the platform, not the guard

    async def test_a_chat_with_a_hop_that_got_a_5xx_is_the_platform_not_a_verdict(self):
        async with generator() as (platform, runner, clock):
            platform.ace_script = lambda who, text: ("not available", [llm_row("HTTP 504", "error", 504)])
            result = await run(runner, "alice-accounts")
            self.assertEqual((result.status, result.detail), (FAILED, "Ace's llm acme-chat got HTTP 504"))
            self.assertEqual(runner._trouble["alice-accounts"], 1)

    async def test_a_token_the_gateway_refused_is_replaced_without_a_failure(self):
        async with generator() as (platform, runner, clock):
            await run(runner, "alice-reads-her-accounts")
            platform.revoke_every_token()
            for name in ("alice-reads-her-accounts", "bob-balance"):
                self.assertEqual((await run(runner, name)).status, OK, name)


class Budgets(unittest.IsolatedAsyncioTestCase):
    async def test_a_scenario_that_would_pass_40_percent_of_a_budget_is_skipped_and_calls_nothing(self):
        async with generator() as (platform, runner, clock):
            runner.world.ledger.charge("team-fraud", 0.795)
            result = await runner.run_one(named(runner, "fraud-analytics-asks"))
            self.assertEqual(result.status, SKIPPED)
            self.assertIn("team-fraud: 40% of 2.00 USD a day used, the traffic keeps to 40%", result.detail)
            self.assertEqual(platform.seen("/acme-bank-teams"), [])

    async def test_a_chat_is_skipped_when_the_plan_of_ace_is_nearly_at_its_share(self):
        async with generator() as (platform, runner, clock):
            runner.world.ledger.charge("ace", 399_000)
            result = await runner.run_one(named(runner, "alice-accounts"))
            self.assertEqual(result.status, SKIPPED)
            self.assertEqual(platform.seen("/acme-bank/ace"), [])
            self.assertEqual((await runner.run_one(named(runner, "alice-reads-her-accounts"))).status, OK)    # free

    async def test_what_a_workspace_call_cost_is_charged_in_dollars(self):
        async with generator() as (platform, runner, clock):
            await runner.run_one(named(runner, "customer-care-asks"))
            self.assertAlmostEqual(runner.world.ledger.used("team-care"), 70 * 50 / 1e6)      # 70 tokens at the demo price

    async def test_the_gateways_own_count_is_what_the_traffic_goes_by(self):
        async with generator() as (platform, runner, clock):
            platform.spent["team-care"] = 3.0                         # the Teams tab of the web app spent 60%
            await runner.run_one(named(runner, "customer-care-asks"))
            self.assertGreaterEqual(runner.world.ledger.used("team-care"), 3.0)
            result = await runner.run_one(named(runner, "customer-care-asks"))
            self.assertEqual(result.status, SKIPPED)
            self.assertEqual(len(platform.seen("/acme-bank-teams/chat")), 1)

    async def test_a_429_from_a_budget_that_somebody_else_spent_is_a_skip(self):
        async with generator() as (platform, runner, clock):
            platform.spent["team-care"] = 5.0
            result = await runner.run_one(named(runner, "customer-care-asks"))
            self.assertEqual(result.status, SKIPPED)
            self.assertIn("Cost budget exceeded", result.detail)

    async def test_the_traffic_key_does_not_pass_its_share_of_3000_tokens_a_minute(self):
        async with generator() as (platform, runner, clock):
            platform.answer_tokens = (400, 400)
            statuses = [(await runner.run_one(named(runner, "faq-on-the-traffic-key"))).status for _ in range(3)]
            self.assertEqual(statuses[:1], [OK])
            self.assertIn(SKIPPED, statuses)
            self.assertLessEqual(runner.world.ledger.used("traffic"), 1_200 + 800)     # at most one call over the share


class WhenTheKeyChanges(unittest.IsolatedAsyncioTestCase):
    async def test_a_team_whose_key_changed_is_asked_again_with_the_new_one(self):
        async with generator() as (platform, runner, clock):
            await runner.run_one(named(runner, "customer-care-asks"))
            platform.team_keys["team-care"] = "key-care-rotated"
            result = await runner.run_one(named(runner, "customer-care-asks"))
            self.assertEqual(result.status, OK)

    async def test_a_key_that_stays_refused_is_the_platform_not_a_verdict(self):
        async with generator() as (platform, runner, clock):
            platform.stale_keys["team-care"] = "stale"
            result = await runner.run_one(named(runner, "customer-care-asks"))
            self.assertEqual(result.status, FAILED)
            self.assertIn("HTTP 401", result.detail)


if __name__ == "__main__":
    unittest.main()
