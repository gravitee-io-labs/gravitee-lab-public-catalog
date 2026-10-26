"""The orders the page sends: realistic enough to filter on, to reshape and to encrypt."""
import itertools
import random
import time

CUSTOMERS = [
    ("Léa Martin", "FR"), ("Noah Fischer", "DE"), ("Sofía Ortega", "ES"), ("Emma Rossi", "IT"),
    ("Liam Brooks", "US"), ("Amélie Dubois", "FR"), ("Jonas Weber", "DE"), ("Carmen Ruiz", "ES"),
]
CARDS = ["4111111111111111", "5500000000000004", "4242424242424242", "4012888888881881", "378282246310005"]
COUNTRIES = ("FR", "DE", "ES", "IT", "US")
_counter = itertools.count(int(time.time()) % 100000 + 1000)
LARGE_BYTES = 120 * 1024            # an order with its scanned invoice: over the 50 KB the gateway offloads from


def email_of(name: str) -> str:
    plain = name.lower().replace(" ", ".").translate(str.maketrans("éèêàáçíñóúü", "eeeaacinouu"))
    return f"{plain}@example.test"


def make(customer: str | None = None, country: str | None = None, amount: float | None = None, large: bool = False,
         rng: random.Random | None = None) -> dict:
    """One order. Anything not given is picked at random. `large` adds an invoice that makes it 120 KB."""
    rng = rng or random
    name, home = rng.choice(CUSTOMERS) if not customer else (customer, country or "FR")
    order = {
        "orderId": f"ORD-{next(_counter)}",
        "customer": name,
        "email": email_of(name),
        "country": country or home,
        "amount": round(amount if amount is not None else rng.choice([29.9, 49.0, 129.9, 249.0, 640.0, 820.0, 1500.0, 2400.0]), 2),
        "currency": "EUR",
        "card": rng.choice(CARDS),
        "status": "CREATED",
    }
    if large:
        order["invoice"] = "JVBERi0xLjQK" * (LARGE_BYTES // 12)       # stands for the scanned invoice, base64
    return order
