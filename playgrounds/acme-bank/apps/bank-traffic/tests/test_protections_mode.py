"""PROTECTIONS tells the generator whether the lessons' protections are on from the start (a presenter's mode) or start switched
off (the lessons). Off, a scenario that a protection decides accepts both outcomes. On, it is strict again: a denial, a block, a
masked IBAN, the 7 tools of a customer, and nothing else is right."""
import unittest
from unittest import mock

import readiness
from checks import FAILED, INCONCLUSIVE, OK
from readiness import MCP
from scenarios import table
from settings import ConfigError, Settings
from tests import fakes
from tests.fakes import ENV, generator, llm_row
from tests.test_scenarios import named, run

# what the policy engine decides, and nothing else does: with it off each of these goes through
POLICY_SCENARIOS = ("bob-reads-alices-accounts", "alice-reads-bobs-accounts", "bob-lists-alices-accounts", "tina-sends-nothing",
                    "alice-freezes-nothing", "alice-sends-12000", "alice-sends-zero-and-less",
                    "alice-hides-bobs-account-behind-her-own", "alice-sends-600-through-ace")


class TheSetting(unittest.TestCase):
    def test_the_protections_are_off_unless_the_compose_file_says_they_are_on(self):
        self.assertFalse(Settings.from_env(ENV).protections)
        self.assertFalse(Settings.from_env({**ENV, "PROTECTIONS": ""}).protections)
        self.assertFalse(Settings.from_env({**ENV, "PROTECTIONS": "off"}).protections)
        self.assertTrue(Settings.from_env({**ENV, "PROTECTIONS": "on"}).protections)
        self.assertTrue(Settings.from_env({**ENV, "PROTECTIONS": "ON"}).protections)

    def test_anything_else_is_said_and_names_the_variable(self):
        with self.assertRaisesRegex(ConfigError, "PROTECTIONS is 'sometimes': use on or off"):
            Settings.from_env({**ENV, "PROTECTIONS": "sometimes"})


class WithTheProtectionsOn(unittest.IsolatedAsyncioTestCase):
    async def test_every_scenario_meets_what_it_expects_when_the_platform_is_protected(self):
        async with generator(PROTECTIONS="on") as (platform, runner, clock):
            for scenario in table(strict=True):
                result = await run(runner, scenario.name)
                self.assertEqual((scenario.name, result.status), (scenario.name, OK), result)

    async def test_the_generator_is_built_strict_from_the_setting(self):
        def answered(who, text):            # the model got the injection
            return "Here is my system prompt", [llm_row()]

        async with generator(PROTECTIONS="on") as (platform, runner, clock):
            platform.ace_script = answered
            self.assertEqual((await run(runner, "injection-through-ace")).status, FAILED)
        async with generator() as (platform, runner, clock):
            platform.ace_script = answered
            self.assertEqual((await run(runner, "injection-through-ace")).status, OK)

    async def test_a_denial_that_became_a_permit_is_a_failure_and_the_money_that_moved_still_comes_back(self):
        with mock.patch.object(fakes, "permitted", lambda *args, **kwargs: True):
            async with generator(PROTECTIONS="on") as (platform, runner, clock):
                before = dict(platform.bank.balances)
                for name in POLICY_SCENARIOS:
                    result = await run(runner, name)
                    self.assertIn(result.status, (FAILED, INCONCLUSIVE), name)
                    if result.status == FAILED:
                        self.assertIn("expected it denied", result.detail, name)
                await runner.world.transfers.settle()
                self.assertEqual(platform.bank.balances, before)
                failed = [name for name in POLICY_SCENARIOS if runner.counters.scenarios[name]["last"]["outcome"] == FAILED]
                self.assertGreaterEqual(len(failed), 6)

    async def test_the_same_permits_are_accepted_when_the_protections_are_off(self):
        with mock.patch.object(fakes, "permitted", lambda *args, **kwargs: True):
            async with generator() as (platform, runner, clock):
                for name in POLICY_SCENARIOS:
                    self.assertIn((await run(runner, name)).status, (OK, INCONCLUSIVE), name)

    async def test_the_log_tells_a_call_that_went_through_from_a_denial_when_the_protections_are_off(self):
        with mock.patch.object(fakes, "permitted", lambda *args, **kwargs: True):
            async with generator() as (platform, runner, clock):
                with self.assertLogs("bank-traffic", "INFO") as logs:
                    for name in ("alice-sends-12000", "alice-reads-bobs-accounts"):
                        await run(runner, name)
        lines = {line.split("scenario=")[1].split(" ")[0]: line for line in logs.output if "scenario=" in line}
        self.assertIn("alice list_accounts went through: the control that decides it is off", lines["alice-reads-bobs-accounts"])
        self.assertIn("alice transfer_funds came back with an error: the control that decides it is off", lines["alice-sends-12000"])   # she has not got 12,000: an error, said as one
        async with generator(PROTECTIONS="on") as (platform, runner, clock):
            with self.assertLogs("bank-traffic", "INFO") as logs:
                await run(runner, "alice-reads-bobs-accounts")
        self.assertNotIn("went through", "\n".join(logs.output))          # denied, as expected: nothing to explain

    async def test_an_injection_the_model_answered_is_a_failure(self):
        async with generator(PROTECTIONS="on") as (platform, runner, clock):
            platform.ace_script = lambda who, text: ("Here is my system prompt", [llm_row()])
            result = await run(runner, "injection-through-ace")
            self.assertEqual((result.status, result.detail), (FAILED, "the guard rails did not stop it"))
            platform.guard_on = False
            result = await run(runner, "injection-on-the-traffic-key")
            self.assertEqual(result.status, FAILED)
            self.assertIn("the guard rails let it through (HTTP 200)", result.detail)

    async def test_an_iban_that_comes_back_in_the_answer_is_a_failure(self):
        async with generator(PROTECTIONS="on") as (platform, runner, clock):
            default = platform.ace_script
            platform.ace_script = lambda who, text: (
                "Your IBAN FR76 3000 6000 0112 3456 7890 189 is on file", default(who, text)[1])
            result = await run(runner, "alice-gives-an-iban")
            self.assertEqual((result.status, result.detail), (FAILED, "the answer repeats what the gateway should have masked"))

    async def test_a_customer_who_sees_freeze_card_is_a_failure(self):
        with mock.patch.dict(fakes.USERS["alice"], {"role": "teller"}):        # a teller's list: 8 tools
            async with generator(PROTECTIONS="on") as (platform, runner, clock):
                result = await run(runner, "who-sees-which-tools")
                self.assertEqual((result.status, result.detail), (FAILED, "alice sees freeze_card"))
            async with generator() as (platform, runner, clock):
                self.assertEqual((await run(runner, "who-sees-which-tools")).status, OK)

    async def test_a_teller_who_does_not_see_freeze_card_is_a_failure_in_both_modes(self):
        with mock.patch.dict(fakes.USERS["tina"], {"role": "customer"}):
            for env in ({}, {"PROTECTIONS": "on"}):
                async with generator(**env) as (platform, runner, clock):
                    result = await run(runner, "who-sees-which-tools")
                    self.assertEqual((result.status, result.detail), (FAILED, "tina does not see freeze_card"), env)

    async def test_the_platform_is_not_ready_for_a_presenter_while_a_customer_lists_eight_tools(self):
        with mock.patch.dict(fakes.USERS["alice"], {"role": "teller"}):
            async with generator(PROTECTIONS="on") as (platform, runner, clock):
                await runner.readiness.check()
                self.assertEqual(runner.readiness.waiting, {MCP: "the MCP proxy lists 8 tools to alice, expected 7"})
            async with generator() as (platform, runner, clock):
                await runner.readiness.check()
                self.assertEqual(runner.readiness.waiting, {})                                    # 7 or 8, as the lessons start

    async def test_a_customer_with_seven_tools_is_ready_in_both_modes(self):
        for env in ({}, {"PROTECTIONS": "on"}):
            async with generator(**env) as (platform, runner, clock):
                await runner.readiness.check()
                self.assertEqual(runner.readiness.waiting, {}, env)
        self.assertEqual(readiness.CUSTOMER_TOOL_COUNT, 7)


class TheScenariosThatCanMoveMoney(unittest.IsolatedAsyncioTestCase):
    """With the policy engine off a scenario that expects a denial moves money (Tina sends EUR 50, Alice EUR 12,000 if she had it):
    it is watched like the others, so a call cut after the bank acted is found and given back."""

    def test_every_scenario_that_may_move_money_says_so(self):
        moving = {s.name for s in table() if s.moves_money}
        self.assertEqual(moving, {"alice-sends-120", "alice-sends-600-through-ace", "alice-hides-bobs-account-behind-her-own",
                                  "alice-sends-zero-and-less", "alice-sends-600-herself", "tina-sends-nothing", "alice-sends-12000"})
        self.assertEqual({s.name for s in table(strict=True) if s.moves_money}, moving)

    async def test_a_transfer_tina_made_with_the_policy_engine_off_and_whose_answer_was_lost_is_found_and_given_back(self):
        with mock.patch.object(fakes, "permitted", lambda *args, **kwargs: True):
            async with generator() as (platform, runner, clock):
                before = dict(platform.bank.balances)
                platform.broken_transfers["tina"] = True              # the bank moved the money, the gateway lost the answer
                result = await runner.run_one(named(runner, "tina-sends-nothing"))
                self.assertEqual(result.status, FAILED)
                self.assertNotEqual(platform.bank.balances, before)    # the money moved
                await runner.world.transfers.settle()
                self.assertEqual(platform.bank.balances, before)       # and is back

    async def test_no_new_transfer_starts_while_one_is_owed(self):
        async with generator() as (platform, runner, clock):
            await runner.readiness.check()
            names = ("tina-sends-nothing", "alice-sends-12000")
            self.assertTrue(all(runner._allowed(named(runner, name)) for name in names))
            runner.world.transfers.note("ACC-1001", "ACC-2001", 50)
            for name in names:
                self.assertFalse(runner._allowed(named(runner, name)), name)
