"""The bank's data: accounts, transactions, transfers and cards."""
import sys
import threading
import unittest
from datetime import date

from mcp.server.mcpserver.exceptions import ToolError

import data
from data import Bank

TODAY = date(2026, 10, 1)
CATEGORIES = {"groceries", "rent", "salary", "transport", "restaurants", "subscriptions", "utilities", "interest",
              "transfer"}


class Accounts(unittest.TestCase):
    def setUp(self):
        self.bank = Bank(TODAY)

    def test_a_customer_has_the_accounts_of_the_story(self):
        alice = self.bank.list_accounts("C-1001")
        self.assertEqual(alice["name"], "Alice Martin")
        self.assertEqual([(a["account_id"], a["type"], a["balance"]) for a in alice["accounts"]],
                         [("ACC-1001", "checking", 4820.55), ("ACC-1002", "savings", 15300.00)])
        self.assertEqual(self.bank.list_accounts("C-2001")["accounts"][0]["balance"], 920.10)

    def test_the_traffic_customer_is_separate_from_the_story(self):
        traffic = self.bank.list_accounts("C-9001")
        self.assertEqual([a["account_id"] for a in traffic["accounts"]], ["ACC-9001"])
        self.assertIn("CARD-9001", data.CARDS)

    def test_ids_are_read_in_any_case_with_spaces_around(self):
        self.assertEqual(self.bank.get_balance(" acc-2001 ")["account_id"], "ACC-2001")
        self.assertEqual(self.bank.list_accounts("c-2001")["customer_id"], "C-2001")

    def test_unknown_ids_say_what_an_id_looks_like(self):
        for call, expected in ((lambda: self.bank.list_accounts("C-0"), "C- followed by digits"),
                               (lambda: self.bank.get_balance("ACC-0"), "ACC- followed by digits"),
                               (lambda: self.bank.freeze_card("CARD-0", "x"), "CARD- followed by digits")):
            with self.subTest(expected=expected), self.assertRaisesRegex(ToolError, expected):
                call()


class Transactions(unittest.TestCase):
    def setUp(self):
        self.bank = Bank(TODAY)

    def test_every_account_has_twelve_to_fifteen_rows_newest_first(self):
        for account_id in data.ACCOUNTS:
            with self.subTest(account=account_id):
                rows = self.bank.list_transactions(account_id, 50, None)["transactions"]
                self.assertTrue(12 <= len(rows) <= 15, len(rows))
                dates = [row["date"] for row in rows]
                self.assertEqual(dates, sorted(dates, reverse=True))
                self.assertLess(dates[0], TODAY.isoformat())
                self.assertTrue({row["category"] for row in rows} <= CATEGORIES)

    def test_dates_count_back_from_the_day_given(self):
        first = self.bank.list_transactions("ACC-1001", 1, None)["transactions"][0]
        self.assertEqual(first["date"], "2026-09-30")
        later = Bank(date(2026, 12, 1)).list_transactions("ACC-1001", 1, None)["transactions"][0]
        self.assertEqual(later["date"], "2026-11-30")

    def test_transaction_ids_are_unique(self):
        ids = [row["id"] for account_id in data.ACCOUNTS
               for row in self.bank.list_transactions(account_id, 50, None)["transactions"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[0], "TX-1001-01")

    def test_the_default_listing_gives_a_count_and_a_total(self):
        result = self.bank.list_transactions("ACC-1001", 3, None)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["total"], round(-63.40 - 14.90 - 42.00, 2))

    def test_a_category_narrows_the_rows_and_the_total(self):
        result = self.bank.list_transactions("ACC-1001", 10, "Groceries")
        self.assertEqual({row["category"] for row in result["transactions"]}, {"groceries"})
        self.assertEqual(result["total"], round(-63.40 - 27.85 - 51.30, 2))
        self.assertEqual(self.bank.list_transactions("ACC-1001", 10, "nothing")["count"], 0)

    def test_the_limit_stays_between_one_and_fifty(self):
        self.assertEqual(self.bank.list_transactions("ACC-1001", 0, None)["count"], 1)
        self.assertEqual(self.bank.list_transactions("ACC-1001", 500, None)["count"], 14)


class Transfers(unittest.TestCase):
    def setUp(self):
        self.bank = Bank(TODAY)

    def balance(self, account_id):
        return self.bank.get_balance(account_id)["balance"]

    def test_money_moves_from_one_account_to_the_other(self):
        done = self.bank.transfer("ACC-1001", "ACC-2001", 120, "rent share")
        self.assertEqual((done["from_account"], done["to_account"], done["amount"], done["new_balance"]),
                         ("ACC-1001", "ACC-2001", 120, 4700.55))
        self.assertEqual(done["reference"], "rent share")
        self.assertEqual((self.balance("ACC-1001"), self.balance("ACC-2001")), (4700.55, 1040.10))

    def test_confirmation_ids_count_up(self):
        first = self.bank.transfer("ACC-9001", "ACC-1001", 1, "")
        second = self.bank.transfer("ACC-9001", "ACC-1001", 1, "")
        self.assertEqual((first["confirmation_id"], second["confirmation_id"]), ("TRF-000001", "TRF-000002"))

    def test_the_server_enforces_funds_not_limits(self):
        # limits are the gateway's job: calling the server directly is the unprotected case the playground shows
        self.bank.transfer("ACC-9001", "ACC-1001", 12000, "")
        self.assertEqual(self.balance("ACC-9001"), 13000)
        with self.assertRaisesRegex(ToolError, "Insufficient funds: the balance is 920.10 EUR"):
            self.bank.transfer("ACC-2001", "ACC-1001", 920.11, "")
        self.assertEqual(self.balance("ACC-2001"), 920.10)

    def test_a_transfer_needs_two_known_different_accounts(self):
        with self.assertRaisesRegex(ToolError, "Unknown account ACC-0"):
            self.bank.transfer("ACC-1001", "ACC-0", 5, "")
        with self.assertRaisesRegex(ToolError, "two different accounts"):
            self.bank.transfer("ACC-1001", "acc-1001", 5, "")
        self.assertEqual(self.balance("ACC-1001"), 4820.55)

    def test_an_amount_has_at_most_two_decimals(self):
        self.bank.transfer("ACC-1001", "ACC-2001", 10.25, "")
        with self.assertRaisesRegex(ToolError, "at most two decimals"):
            self.bank.transfer("ACC-1001", "ACC-2001", 10.255, "")

    def test_concurrent_transfers_lose_nothing(self):
        # a tiny switch interval makes the threads interleave inside a transfer, where a missing lock loses money
        interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        self.addCleanup(sys.setswitchinterval, interval)

        def move_fifty_euros():
            for _ in range(50):
                self.bank.transfer("ACC-9001", "ACC-1001", 1, "")

        threads = [threading.Thread(target=move_fifty_euros) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((self.balance("ACC-9001"), self.balance("ACC-1001")), (24600, 5220.55))

    def test_reset_puts_balances_cards_and_the_counter_back(self):
        self.bank.transfer("ACC-1001", "ACC-2001", 600, "")
        self.bank.freeze_card("CARD-1001", "stolen")
        self.bank.reset()
        self.assertEqual((self.balance("ACC-1001"), self.balance("ACC-2001")), (4820.55, 920.10))
        self.assertEqual(self.bank.freeze_card("CARD-1001", "stolen")["previous_status"], "ACTIVE")
        self.assertEqual(self.bank.transfer("ACC-1001", "ACC-2001", 1, "")["confirmation_id"], "TRF-000001")


class Cards(unittest.TestCase):
    def test_freezing_is_repeatable_and_says_what_the_card_was(self):
        bank = Bank(TODAY)
        first = bank.freeze_card("card-9001", "lost")
        again = bank.freeze_card("CARD-9001", "lost")
        self.assertEqual((first["status"], first["previous_status"]), ("FROZEN", "ACTIVE"))
        self.assertEqual((again["status"], again["previous_status"]), ("FROZEN", "FROZEN"))
        self.assertEqual(Bank(TODAY).freeze_card("CARD-2001", "x")["previous_status"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
