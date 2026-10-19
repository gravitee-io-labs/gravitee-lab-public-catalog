"""The budget arithmetic: the traffic never takes more than 40% of a limit, and the default pace is far below that."""
import unittest

from ledger import DAY, HOUR, Ledger, cost_usd
from runner import Pace
from scenarios import table


class Caps(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.ledger = Ledger(clock=lambda: self.now)

    def test_a_spend_under_the_share_is_allowed_and_one_over_it_is_not(self):
        self.assertIsNone(self.ledger.refusal({"ace": 400_000}))      # 40% of 1,000,000 tokens an hour
        self.assertIn("40%", self.ledger.refusal({"ace": 400_001}))

    def test_what_was_spent_counts(self):
        self.ledger.charge("ace", 399_000)
        self.assertIsNone(self.ledger.refusal({"ace": 1_000}))
        self.assertIn("ace: 40% of 1,000,000 tokens an hour used", self.ledger.refusal({"ace": 2_000}))

    def test_a_scenario_that_spends_from_two_limits_needs_both(self):
        self.ledger.charge("team-care", 2.0)
        self.assertIn("team-care", self.ledger.refusal({"ace": 100, "team-care": 0.01}))

    def test_the_window_rolls(self):
        self.ledger.charge("traffic", 1_200)                          # 40% of 3,000 tokens a minute
        self.assertIsNotNone(self.ledger.refusal({"traffic": 1}))
        self.now += 59
        self.assertIsNotNone(self.ledger.refusal({"traffic": 1}))
        self.now += 2
        self.assertIsNone(self.ledger.refusal({"traffic": 1}))

    def test_a_budget_in_dollars_has_a_day_window(self):
        self.ledger.charge("team-fraud", 0.79)                        # 40% of 2.00 dollars a day is 0.80
        self.assertIsNone(self.ledger.refusal({"team-fraud": 0.01}))
        self.assertIsNotNone(self.ledger.refusal({"team-fraud": 0.02}))
        self.now += DAY - 1
        self.assertIsNotNone(self.ledger.refusal({"team-fraud": 0.02}))
        self.now += 2
        self.assertIsNone(self.ledger.refusal({"team-fraud": 0.02}))

    def test_what_the_gateway_counted_is_a_floor_for_a_while(self):
        """Somebody else may spend from the same budget: the gateway's own count is what the traffic goes by."""
        self.ledger.observe("team-care", limit=5.0, remaining=2.5, seconds_left=100)       # 2.50 of 5.00 used
        self.assertEqual(self.ledger.used("team-care"), 2.5)
        self.assertIsNotNone(self.ledger.refusal({"team-care": 0.01}))
        self.now += 101
        self.assertIsNone(self.ledger.refusal({"team-care": 0.01}))

    def test_the_gateways_count_never_lowers_the_traffics_own(self):
        self.ledger.charge("team-care", 1.5)
        self.ledger.observe("team-care", limit=5.0, remaining=4.5, seconds_left=100)       # 0.50 used
        self.assertEqual(self.ledger.used("team-care"), 1.5)

    def test_the_limit_the_gateway_announces_replaces_the_default(self):
        self.ledger.observe("traffic", limit=6_000, remaining=6_000, seconds_left=None)
        self.assertIsNone(self.ledger.refusal({"traffic": 2_400}))
        self.assertIsNotNone(self.ledger.refusal({"traffic": 2_401}))

    def test_a_429_leaves_the_limit_alone_until_it_is_over(self):
        self.ledger.block("ace", 300)
        self.assertIn("refuses", self.ledger.refusal({"ace": 1}))
        self.now += 301
        self.assertIsNone(self.ledger.refusal({"ace": 1}))

    def test_the_snapshot_says_how_much_of_each_limit_is_used(self):
        self.ledger.charge("ace", 100_000)
        self.assertEqual(self.ledger.snapshot()["ace"],
                         {"unit": "tokens", "limit": 1_000_000, "window_seconds": HOUR, "used": 100_000,
                          "cap": 400_000, "percent": 10.0})


class Prices(unittest.TestCase):
    def test_the_demo_prices(self):
        self.assertAlmostEqual(cost_usd("smart", 1_000, 0), 0.05)          # 50 dollars per million tokens
        self.assertAlmostEqual(cost_usd("lite", 500, 500), 0.02)           # 20 dollars per million tokens
        self.assertAlmostEqual(cost_usd("qwen3:0.6b", 1_000, 0), 0.02)

    def test_a_model_it_does_not_know_is_priced_as_the_dearer_one(self):
        self.assertAlmostEqual(cost_usd("something-new", 1_000, 0), 0.05)


class DefaultPace(unittest.TestCase):
    """The arithmetic of the compose comment of TRAFFIC_RATE, as code: at rate 1 what the table spends in a window
    stays under 40% of every limit, with room to spare."""

    def spend_per_hour(self):
        scenarios = table()
        per_hour = 3600 / Pace().interval
        weight = sum(s.weight for s in scenarios)
        spend = {}
        for s in scenarios:
            for limit, amount in s.estimate.items():
                spend[limit] = spend.get(limit, 0) + s.weight / weight * per_hour * amount
        return spend

    def test_ace_chats_stay_under_twenty_an_hour(self):
        chats = sum(s.weight for s in table() if {"a2a", "mcp", "llm"} <= s.needs)
        self.assertLess(chats / sum(s.weight for s in table()) * 3600 / Pace().interval, 20)

    def test_every_limit_keeps_room(self):
        caps = Ledger().snapshot()
        spend = self.spend_per_hour()
        self.assertLess(spend["ace"], 0.1 * caps["ace"]["limit"])                            # an hour
        self.assertLess(spend["traffic"] / 60, 0.1 * caps["traffic"]["limit"])               # a minute
        self.assertLess(spend["team-care"] * 24, 0.4 * caps["team-care"]["limit"])           # a day
        self.assertLess(spend["team-fraud"] * 24, 0.4 * caps["team-fraud"]["limit"])


if __name__ == "__main__":
    unittest.main()
