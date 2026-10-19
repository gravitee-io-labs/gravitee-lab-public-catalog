"""The bank's own data: customers, accounts, cards and transactions, kept in memory.

It is the same at every start: same ids, balances and rows. Transaction dates are counted back from the day the
container started, so the last weeks always have rows. `Bank.reset()` puts balances, cards and the transfer counter
back; the transaction history is fixed data and transfers do not add to it.
"""
import itertools
import threading
from datetime import timedelta

from mcp.server.mcpserver.exceptions import ToolError

CURRENCY = "EUR"

# C-9001 is not part of the story: the traffic generator freezes its card and moves its money, so the story's
# customers keep their balances and their cards
CUSTOMERS = {"C-1001": "Alice Martin", "C-2001": "Bob Chen", "C-9001": "Traffic Test"}

ACCOUNTS = {
    "ACC-1001": {"customer_id": "C-1001", "type": "checking", "balance": 4820.55},
    "ACC-1002": {"customer_id": "C-1001", "type": "savings", "balance": 15300.00},
    "ACC-2001": {"customer_id": "C-2001", "type": "checking", "balance": 920.10},
    "ACC-9001": {"customer_id": "C-9001", "type": "checking", "balance": 25000.00},
}

CARDS = {"CARD-1001": "C-1001", "CARD-2001": "C-2001", "CARD-9001": "C-9001"}

# Per account, newest first: days before the container started, description, category, amount in EUR
HISTORY = {
    "ACC-1001": [
        (1, "Carrefour Market", "groceries", -63.40), (2, "Metro Paris", "transport", -14.90),
        (4, "Le Bistrot", "restaurants", -42.00), (6, "Netflix", "subscriptions", -13.49),
        (8, "EDF", "utilities", -78.20), (10, "Franprix", "groceries", -27.85),
        (12, "SNCF", "transport", -58.00), (15, "ACME Corp salary", "salary", 3100.00),
        (17, "Landlord SCI Lumiere", "rent", -1150.00), (19, "Spotify", "subscriptions", -10.99),
        (21, "Monoprix", "groceries", -51.30), (24, "Brasserie Lipp", "restaurants", -67.50),
        (27, "Orange", "utilities", -39.99), (30, "Uber", "transport", -18.40),
    ],
    "ACC-1002": [
        (5, "Interest", "interest", 12.75), (20, "Transfer from ACC-1001", "transfer", 500.00),
        (35, "Interest", "interest", 12.60), (50, "Transfer from ACC-1001", "transfer", 500.00),
        (65, "Interest", "interest", 12.45), (80, "Transfer from ACC-1001", "transfer", 500.00),
        (95, "Interest", "interest", 12.30), (110, "Transfer from ACC-1001", "transfer", 1000.00),
        (125, "Interest", "interest", 12.10), (140, "Transfer from ACC-1001", "transfer", 750.00),
        (155, "Interest", "interest", 11.95), (170, "Transfer from ACC-1001", "transfer", 500.00),
    ],
    "ACC-2001": [
        (1, "Lidl", "groceries", -34.20), (3, "Deliveroo", "restaurants", -23.90),
        (5, "RATP", "transport", -75.20), (7, "Amazon Prime", "subscriptions", -6.99),
        (9, "Engie", "utilities", -61.35), (11, "Carrefour", "groceries", -48.10),
        (14, "Bolt", "transport", -12.40), (15, "Studio Nord salary", "salary", 2250.00),
        (16, "Agence Foncia", "rent", -980.00), (18, "Disney+", "subscriptions", -9.99),
        (22, "Picard", "groceries", -29.70), (25, "Pizza Roma", "restaurants", -31.50),
    ],
    "ACC-9001": [
        (1, "Auchan", "groceries", -58.30), (2, "Bus Lyon TCL", "transport", -9.50),
        (4, "Chez Paul", "restaurants", -36.80), (6, "Canal+", "subscriptions", -19.99),
        (9, "Veolia", "utilities", -44.10), (11, "Intermarche", "groceries", -72.45),
        (13, "SNCF", "transport", -39.00), (15, "ACME Labs salary", "salary", 2800.00),
        (16, "Agence Century 21", "rent", -890.00), (20, "Dejeuner Express", "restaurants", -14.20),
        (23, "Free", "utilities", -15.99), (26, "Cora", "groceries", -63.15),
    ],
}


def normalize(identifier):
    """Models send ids in any case and with spaces around: ' acc-1001' is ACC-1001."""
    return identifier.strip().upper()


def _transactions(account_id, today):
    return [
        {"id": f"TX-{account_id[-4:]}-{number:02d}", "date": (today - timedelta(days=days)).isoformat(),
         "description": description, "category": category, "amount": amount, "currency": CURRENCY}
        for number, (days, description, category, amount) in enumerate(HISTORY[account_id], start=1)
    ]


class Bank:
    """The state behind the tools. Tools run in worker threads, so what changes is changed under a lock."""

    def __init__(self, today):
        self._lock = threading.Lock()
        self._transactions = {account_id: _transactions(account_id, today) for account_id in ACCOUNTS}
        self.reset()

    def reset(self):
        with self._lock:
            self._balances = {account_id: account["balance"] for account_id, account in ACCOUNTS.items()}
            self._card_status = {card_id: "ACTIVE" for card_id in CARDS}
            self._confirmations = itertools.count(1)

    def list_accounts(self, customer_id):
        customer_id = normalize(customer_id)
        if customer_id not in CUSTOMERS:
            raise ToolError(f"Unknown customer {customer_id}. A customer id is C- followed by digits.")
        accounts = [{"account_id": account_id, "type": account["type"], "currency": CURRENCY,
                     "balance": self._balances[account_id]}
                    for account_id, account in ACCOUNTS.items() if account["customer_id"] == customer_id]
        return {"customer_id": customer_id, "name": CUSTOMERS[customer_id], "accounts": accounts}

    def get_balance(self, account_id):
        account_id = self._known_account(account_id)
        return {"account_id": account_id, "balance": self._balances[account_id], "currency": CURRENCY}

    def list_transactions(self, account_id, limit, category):
        account_id = self._known_account(account_id)
        rows = self._transactions[account_id]
        if category:
            rows = [row for row in rows if row["category"] == category.strip().lower()]
        rows = rows[: max(1, min(limit, 50))]
        # count and total save the model from adding the rows up itself, which it does badly
        return {"account_id": account_id, "count": len(rows), "total": round(sum(row["amount"] for row in rows), 2),
                "currency": CURRENCY, "transactions": rows}

    def transfer(self, from_account, to_account, amount, reference):
        if round(amount, 2) != amount:
            raise ToolError("An amount has at most two decimals.")
        with self._lock:
            source, target = self._known_account(from_account), self._known_account(to_account)
            if source == target:
                raise ToolError("Choose two different accounts.")
            if self._balances[source] < amount:
                raise ToolError(f"Insufficient funds: the balance is {self._balances[source]:.2f} {CURRENCY}.")
            self._balances[source] = round(self._balances[source] - amount, 2)
            self._balances[target] = round(self._balances[target] + amount, 2)
            new_balance = self._balances[source]
            confirmation = f"TRF-{next(self._confirmations):06d}"
        return {"confirmation_id": confirmation, "from_account": source, "to_account": target, "amount": amount,
                "currency": CURRENCY, "reference": reference, "new_balance": new_balance}

    def freeze_card(self, card_id, reason):
        card_id = normalize(card_id)
        if card_id not in CARDS:
            raise ToolError(f"Unknown card {card_id}. A card id is CARD- followed by digits.")
        with self._lock:
            previous = self._card_status[card_id]
            self._card_status[card_id] = "FROZEN"
        return {"card_id": card_id, "status": "FROZEN", "previous_status": previous, "reason": reason}

    def _known_account(self, account_id):
        account_id = normalize(account_id)
        if account_id not in ACCOUNTS:
            raise ToolError(f"Unknown account {account_id}. An account id is ACC- followed by digits.")
        return account_id
