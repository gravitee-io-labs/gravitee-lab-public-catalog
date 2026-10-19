"""What the bank tells everyone: exchange rates, loan simulations and branches.

The rates and the branches are the same, by value, as in bank-api/public_data.py. The two apps are separate images, so
the numbers are written twice and both test suites check the same digests and cases.
"""
from datetime import date

from mcp.server.mcpserver.exceptions import ToolError

# What one euro buys; every pair is derived from it
EUR_RATES = {"EUR": 1.0, "USD": 1.0842, "GBP": 0.8567, "CHF": 0.9561, "JPY": 162.38, "CAD": 1.4693, "SEK": 11.2150}
RATE_DATE = date.today().isoformat()

BRANCHES = [
    {"id": "paris-opera", "name": "ACME Bank Opera", "city": "Paris",
     "address": "12 Rue des Exemples, 75009 Paris", "hours": "Mon-Fri 09:00-18:00, Sat 09:00-13:00"},
    {"id": "paris-bastille", "name": "ACME Bank Bastille", "city": "Paris",
     "address": "5 Rue du Test, 75011 Paris", "hours": "Mon-Fri 09:30-17:30"},
    {"id": "lyon-bellecour", "name": "ACME Bank Bellecour", "city": "Lyon",
     "address": "8 Place de la Demo, 69002 Lyon", "hours": "Mon-Fri 09:00-18:00, Sat 09:00-12:30"},
    {"id": "marseille-vieux-port", "name": "ACME Bank Vieux-Port", "city": "Marseille",
     "address": "21 Quai des Essais, 13002 Marseille", "hours": "Mon-Fri 09:00-17:30"},
    {"id": "lille-grand-place", "name": "ACME Bank Grand Place", "city": "Lille",
     "address": "3 Place des Maquettes, 59800 Lille", "hours": "Mon-Sat 09:00-17:00"},
    {"id": "bordeaux-chartrons", "name": "ACME Bank Chartrons", "city": "Bordeaux",
     "address": "40 Cours du Prototype, 33300 Bordeaux", "hours": "Mon-Fri 09:00-17:30"},
]


def exchange_rate(base, quote, amount):
    """The rate, and what an amount in `base` comes to in `quote`. A small model that is given a bare rate multiplies
    it badly, so the bank does the sum, and asks for the amount (1 for the plain rate) so the model has to give it.
    It uses the exact rate: shown to four decimals, JPY to EUR is 0.0062 where the exact rate is 0.006158."""
    base, quote = base.strip().upper(), quote.strip().upper()
    if base not in EUR_RATES or quote not in EUR_RATES:
        raise ToolError(f"Unsupported currency. Supported: {', '.join(EUR_RATES)}.")
    rate = EUR_RATES[quote] / EUR_RATES[base]
    return {"base": base, "quote": quote, "rate": round(rate, 4), "converted": round(amount * rate, 2),
            "date": RATE_DATE}


def simulate_loan(amount, years, annual_rate_percent):
    if years <= 0 or annual_rate_percent < 0:
        raise ToolError("The duration must be positive and the rate cannot be negative.")
    months, monthly_rate = years * 12, annual_rate_percent / 100 / 12
    if monthly_rate == 0:
        monthly = amount / months
    else:
        monthly = amount * monthly_rate / (1 - (1 + monthly_rate) ** -months)
    return {"amount": amount, "years": years, "annual_rate_percent": annual_rate_percent,
            "monthly_payment": round(monthly, 2), "total_cost": round(monthly * months, 2),
            "total_interest": round(monthly * months - amount, 2), "currency": "EUR"}


def find_branches(city):
    city = city.strip()
    found = [branch for branch in BRANCHES if branch["city"].lower() == city.lower()]
    if found:
        return {"city": found[0]["city"], "count": len(found), "branches": found}
    cities = sorted({branch["city"] for branch in BRANCHES})
    note = f"No branch in {city}. Cities with a branch: {', '.join(cities)}."
    return {"city": city, "count": 0, "branches": [], "note": note}
