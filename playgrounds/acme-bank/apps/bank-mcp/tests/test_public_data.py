"""What the bank tells everyone: exchange rates, loans and branches."""
import hashlib
import json
import unittest
from datetime import date

from mcp.server.mcpserver.exceptions import ToolError

import public_data

# bank-api's tests hold the same pairs and the same digests: the two apps keep the same rates and branches by value.
# A digest that no longer matches means a table changed here and not there, or the other way round.
RATES_DIGEST = "6d57a22b303c1e184b023c37d1ecb2aecaedae4c273de6bd05db70841954535d"
BRANCHES_DIGEST = "c5ed3c59fe4f020d064199d80012c1dcef932487af7da93a1738379eab398561"
RATE_CASES = [("EUR", "USD", 1.0842), ("USD", "EUR", 0.9223), ("EUR", "GBP", 0.8567), ("GBP", "EUR", 1.1673),
              ("USD", "JPY", 149.7694), ("CHF", "SEK", 11.7299), ("CAD", "CAD", 1.0)]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class SharedTables(unittest.TestCase):
    def test_the_tables_are_the_ones_of_bank_api(self):
        self.assertEqual(digest(public_data.EUR_RATES), RATES_DIGEST)
        self.assertEqual(digest(public_data.BRANCHES), BRANCHES_DIGEST)


class ExchangeRates(unittest.TestCase):
    def test_every_pair_is_derived_from_the_euro_table(self):
        for base, quote, rate in RATE_CASES:
            with self.subTest(pair=f"{base}/{quote}"):
                self.assertEqual(public_data.exchange_rate(base, quote, 1)["rate"], rate)

    def test_an_amount_comes_back_converted_to_two_decimals(self):
        """2,500 and 1,250.50 EUR in USD are sums a small model gets wrong when it multiplies the rate itself."""
        for base, quote, amount, converted in [("EUR", "USD", 100, 108.42), ("EUR", "USD", 2500, 2710.50),
                                               ("EUR", "USD", 1250.50, 1355.79), ("USD", "EUR", 100, 92.23),
                                               ("USD", "JPY", 250, 37442.35), ("CAD", "SEK", 80, 610.63),
                                               ("GBP", "GBP", 10.456, 10.46)]:
            with self.subTest(case=f"{amount} {base}/{quote}"):
                result = public_data.exchange_rate(base, quote, amount)
                self.assertEqual(result["converted"], converted)
                self.assertEqual(result["rate"], public_data.exchange_rate(base, quote, 1)["rate"])

    def test_the_conversion_uses_the_exact_rate_not_the_one_shown_to_four_decimals(self):
        """JPY to EUR is shown as 0.0062: that rate would give 62.00 for 10,000 JPY, the exact one gives 61.58."""
        result = public_data.exchange_rate("JPY", "EUR", 10000)
        self.assertEqual((result["rate"], result["converted"]), (0.0062, 61.58))

    def test_an_amount_of_one_is_the_plain_rate(self):
        result = public_data.exchange_rate("EUR", "USD", 1)
        self.assertEqual((result["rate"], result["converted"]), (1.0842, 1.08))

    def test_codes_are_read_in_any_case_and_the_rate_has_a_date(self):
        result = public_data.exchange_rate(" usd ", "jpy", 1)
        self.assertEqual((result["base"], result["quote"]), ("USD", "JPY"))
        date.fromisoformat(result["date"])

    def test_an_unsupported_currency_lists_the_supported_ones(self):
        with self.assertRaisesRegex(ToolError, "Unsupported currency. Supported: EUR, USD, GBP, CHF, JPY, CAD, SEK"):
            public_data.exchange_rate("EUR", "XYZ", 1)


class Loans(unittest.TestCase):
    def test_a_loan_at_the_default_rate(self):
        loan = public_data.simulate_loan(10000, 5, 4.2)
        self.assertEqual(loan["monthly_payment"], 185.07)
        self.assertEqual(loan["total_cost"], 11104.15)
        self.assertEqual(loan["total_interest"], 1104.15)

    def test_a_loan_without_interest_is_split_evenly(self):
        loan = public_data.simulate_loan(12000, 2, 0)
        self.assertEqual((loan["monthly_payment"], loan["total_interest"]), (500.0, 0.0))

    def test_a_loan_needs_a_duration_and_no_negative_rate(self):
        for years, rate in ((0, 4.2), (-1, 4.2), (5, -1)):
            with self.subTest(years=years, rate=rate), self.assertRaises(ToolError):
                public_data.simulate_loan(1000, years, rate)


class Branches(unittest.TestCase):
    def test_a_city_lists_its_branches(self):
        paris = public_data.find_branches(" paris ")
        self.assertEqual((paris["city"], paris["count"]), ("Paris", 2))
        self.assertEqual({b["id"] for b in paris["branches"]}, {"paris-opera", "paris-bastille"})

    def test_a_city_without_a_branch_names_the_ones_with_a_branch(self):
        nowhere = public_data.find_branches("Atlantis")
        self.assertEqual((nowhere["count"], nowhere["branches"]), (0, []))
        self.assertIn("Bordeaux, Lille, Lyon, Marseille, Paris", nowhere["note"])


if __name__ == "__main__":
    unittest.main()
