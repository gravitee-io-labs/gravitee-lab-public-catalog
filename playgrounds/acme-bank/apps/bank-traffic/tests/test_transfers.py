"""Money that moves with no answer: a call that ends in the middle (the gateway gives up, a scenario is cut, a restart
of the platform) may have moved it, and the story's balances must still end where they started."""
import asyncio
import unittest

from checks import FAILED
from readiness import MCP
from runner import Pace
from scenarios import Scenario
from tests.fakes import generator
from wire import PlatformError

STORY = {"ACC-1001": 4820.55, "ACC-1002": 15300.0, "ACC-2001": 920.10}


def story(platform):
    return {account: platform.bank.balances[account] for account in STORY}


def debts(transfers):
    return [(d.source, d.target, d.amount) for d in transfers.owed]


async def settled(runner, name):
    result = await runner.run_one(next(s for s in runner.scenarios if s.name == name))
    await runner.world.transfers.settle()
    return result


class AScenarioThatEndsWithoutAnAnswer(unittest.IsolatedAsyncioTestCase):
    async def test_what_the_bank_moved_is_found_in_the_balances_and_given_back(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            with self.assertRaises(PlatformError), self.assertLogs("bank-traffic", "WARNING") as logs:
                async with transfers.watch():
                    platform.bank.transfer("ACC-1001", "ACC-2001", 120)
                    raise PlatformError("the gateway gave up")
            self.assertEqual(debts(transfers), [("ACC-1001", "ACC-2001", 120.0)])
            self.assertEqual(logs.output, ["WARNING:bank-traffic:a scenario ended without an answer after 120 EUR went "
                                           "from ACC-1001 to ACC-2001: owed back"])
            await transfers.settle()
            self.assertEqual(story(platform), STORY)
            self.assertEqual(transfers.status(),
                             {"moved_eur": 120.0, "returned_eur": 120.0, "owed": [], "unexplained": []})

    async def test_it_works_in_either_direction_and_between_the_accounts_of_a_customer(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            for source, target, amount in (("ACC-2001", "ACC-1001", 10), ("ACC-1001", "ACC-1002", 25.5)):
                with self.assertRaises(PlatformError), self.assertLogs("bank-traffic", "WARNING"):
                    async with transfers.watch():
                        platform.bank.transfer(source, target, amount)
                        raise PlatformError("the gateway gave up")
                self.assertEqual(debts(transfers), [(source, target, float(amount))])
                await transfers.settle()
                self.assertEqual(story(platform), STORY)

    async def test_a_chat_whose_answer_never_arrives_after_ace_moved_the_money_is_given_back(self):
        async with generator() as (platform, runner, clock):
            real = platform.ace_turn

            def ace(who, text):
                real(who, text)                                    # Ace runs the tool...
                raise RuntimeError("...and the answer never reaches the generator")
            platform.ace_script = ace
            with self.assertLogs("bank-traffic", "WARNING") as logs:
                result = await settled(runner, "alice-sends-120")
            self.assertEqual(result.status, FAILED)
            self.assertIn("120 EUR went from ACC-1001 to ACC-2001: owed back", logs.output[0])
            self.assertEqual(story(platform), STORY)
            self.assertEqual(runner.world.transfers.status()["returned_eur"], 120.0)

    async def test_a_scenario_that_is_cut_for_taking_too_long_is_found_too(self):
        async def moves_then_hangs(world):
            await world.tools.call("alice", "transfer_funds", {"from_account": "ACC-1001", "to_account": "ACC-2001",
                                                               "amount": 120})
            await asyncio.sleep(60)
        async with generator(pace=Pace(timeout=1.5)) as (platform, runner, clock):
            stuck = Scenario("stuck", 1, frozenset({MCP}), moves_then_hangs, {}, True)
            with self.assertLogs("bank-traffic", "WARNING"):
                result = await runner.run_one(stuck)
            self.assertEqual((result.status, result.detail), (FAILED, "no answer in time"))
            self.assertEqual(debts(runner.world.transfers), [("ACC-1001", "ACC-2001", 120.0)])
            await runner.world.transfers.settle()
            self.assertEqual(story(platform), STORY)

    async def test_what_the_scenario_noted_is_not_found_again(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            with self.assertRaises(PlatformError), self.assertLogs("bank-traffic", "WARNING"):
                async with transfers.watch():
                    platform.bank.transfer("ACC-1001", "ACC-2001", 120)
                    transfers.note("ACC-1001", "ACC-2001", 120)           # the scenario knew about this one
                    platform.bank.transfer("ACC-1001", "ACC-2001", 50)    # and not about this one
                    raise PlatformError("the gateway gave up")
            self.assertEqual(debts(transfers), [("ACC-1001", "ACC-2001", 120.0), ("ACC-1001", "ACC-2001", 50.0)])
            await transfers.settle()
            self.assertEqual(story(platform), STORY)

    async def test_a_scenario_that_answered_is_left_alone_whatever_the_balances_did(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            async with transfers.watch():
                platform.bank.transfer("ACC-1001", "ACC-2001", 120)       # somebody else's transfer, as far as it knows
            self.assertEqual((transfers.owed, transfers.unexplained), ([], []))

    async def test_a_scenario_that_moved_nothing_owes_nothing(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            with self.assertRaises(PlatformError):
                async with transfers.watch():
                    raise PlatformError("the gateway gave up")
            self.assertEqual((transfers.owed, transfers.unexplained), ([], []))

    async def test_a_scenario_that_cannot_read_the_balances_first_does_not_start(self):
        async with generator() as (platform, runner, clock):
            platform.mcp_limited = True
            result = await runner.run_one(next(s for s in runner.scenarios if s.name == "alice-sends-120"))
            self.assertEqual(result.status, FAILED)
            self.assertIn("the balance of ACC-1001 cannot be read as alice: rate_limited", result.detail)
            self.assertEqual(platform.seen("/acme-bank/ace"), [])


class WhenWhatMovedCannotBeGivenBack(unittest.IsolatedAsyncioTestCase):
    async def test_balances_that_moved_with_no_single_transfer_to_explain_them_are_said_not_given_back(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            with self.assertRaises(PlatformError), self.assertLogs("bank-traffic", "WARNING") as logs:
                async with transfers.watch():
                    platform.bank.balances["ACC-1001"] -= 50
                    platform.bank.balances["ACC-1002"] += 20
                    platform.bank.balances["ACC-2001"] += 30
                    raise PlatformError("the gateway gave up")
            self.assertEqual(transfers.owed, [])
            message = ("a scenario ended without an answer and the balances moved with no single transfer to explain "
                       "it: ACC-1001 -50.00, ACC-1002 +20.00, ACC-2001 +30.00")
            self.assertEqual(transfers.unexplained, [message])
            self.assertEqual(transfers.status()["unexplained"], [message])
            self.assertEqual(logs.output, [f"WARNING:bank-traffic:{message}; Start the bank over restores the balances"])

    async def test_balances_that_cannot_be_read_afterwards_are_said(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            with self.assertRaises(PlatformError), self.assertLogs("bank-traffic", "WARNING"):
                async with transfers.watch():
                    platform.mcp_limited = True
                    raise PlatformError("the gateway gave up")
            self.assertEqual(transfers.owed, [])
            self.assertEqual(len(transfers.unexplained), 1)
            self.assertIn("the balances could not be read to tell what it moved "
                          "(the balance of ACC-1001 cannot be read as alice: rate_limited", transfers.unexplained[0])

    async def test_only_the_latest_are_kept_and_a_reset_clears_them(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            for _ in range(7):
                with self.assertRaises(PlatformError), self.assertLogs("bank-traffic", "WARNING"):
                    async with transfers.watch():
                        platform.bank.balances["ACC-1001"] -= 1
                        raise PlatformError("the gateway gave up")
            self.assertEqual(len(transfers.unexplained), 5)
            transfers.reset()
            self.assertEqual(transfers.status()["unexplained"], [])

    async def test_a_reset_of_the_demo_during_a_scenario_leaves_nothing_owed(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            platform.bank.balances["ACC-1001"] -= 100                       # the balances are not the story's
            with self.assertRaises(PlatformError):
                async with transfers.watch():
                    platform.bank.transfer("ACC-1001", "ACC-2001", 120)
                    platform.bank.reset()                                   # the bank was reset...
                    transfers.reset()                                       # ...and the generator told so
                    raise PlatformError("the gateway gave up")
            self.assertEqual((transfers.owed, transfers.unexplained), ([], []))


class AGiveBackThatGetsNoAnswer(unittest.IsolatedAsyncioTestCase):
    """The give-back is a transfer too: when its answer is lost it may have gone through, and sending it again would
    move the money a second time."""

    async def test_one_that_went_through_is_recognized_and_not_sent_again(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            platform.bank.transfer("ACC-1001", "ACC-2001", 120)
            transfers.note("ACC-1001", "ACC-2001", 120)
            platform.broken_transfers["bob"] = True                  # the bank gives the money back, the answer is lost
            with self.assertLogs("bank-traffic", "WARNING") as logs:
                await transfers.settle()
            self.assertEqual(debts(transfers), [("ACC-1001", "ACC-2001", 120.0)])
            self.assertIn("transfer of 120 EUR back to ACC-1001 is still owed: the MCP proxy did not answer",
                          logs.output[0])
            self.assertEqual(story(platform), STORY)                  # it did go through
            platform.broken_transfers.clear()
            with self.assertLogs("bank-traffic", "INFO") as logs:
                await transfers.settle()
            self.assertEqual(logs.output, ["INFO:bank-traffic:gave back 120 EUR to ACC-1001"])
            self.assertEqual((transfers.owed, transfers.returned), ([], 120.0))
            self.assertEqual(story(platform), STORY)                  # and it was not sent a second time

    async def test_one_that_never_reached_the_bank_is_sent_again(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            platform.bank.transfer("ACC-1001", "ACC-2001", 120)
            transfers.note("ACC-1001", "ACC-2001", 120)
            platform.broken_transfers["bob"] = False
            with self.assertLogs("bank-traffic", "WARNING"):
                await transfers.settle()
            self.assertEqual(platform.bank.balances["ACC-1001"], 4820.55 - 120)
            platform.broken_transfers.clear()
            await transfers.settle()
            self.assertEqual((transfers.owed, transfers.returned), ([], 120.0))
            self.assertEqual(story(platform), STORY)

    async def test_one_that_failed_twice_and_went_through_the_second_time_is_not_sent_a_third_time(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            platform.bank.transfer("ACC-1001", "ACC-2001", 120)
            transfers.note("ACC-1001", "ACC-2001", 120)
            platform.broken_transfers["bob"] = False
            with self.assertLogs("bank-traffic", "WARNING"):
                await transfers.settle()
            platform.broken_transfers["bob"] = True
            with self.assertLogs("bank-traffic", "WARNING"):
                await transfers.settle()
            platform.broken_transfers.clear()
            await transfers.settle()
            self.assertEqual((transfers.owed, transfers.returned), ([], 120.0))
            self.assertEqual(story(platform), STORY)

    async def test_one_that_the_bank_answered_is_not_taken_for_one_that_went_through(self):
        async with generator() as (platform, runner, clock):
            transfers = runner.world.transfers
            platform.bank.transfer("ACC-1001", "ACC-2001", 120)
            transfers.note("ACC-1001", "ACC-2001", 120)
            platform.bank.balances["ACC-2001"] = 50                  # not enough to give back: the bank says no
            with self.assertLogs("bank-traffic", "WARNING") as logs:
                await transfers.settle()
            self.assertIn("is still owed: error", logs.output[0])
            self.assertIn("Insufficient funds", logs.output[0])
            self.assertIsNone(transfers.owed[0].seen)
            platform.bank.balances["ACC-2001"] = 920.10 + 120
            await transfers.settle()
            self.assertEqual(story(platform), STORY)


if __name__ == "__main__":
    unittest.main()
