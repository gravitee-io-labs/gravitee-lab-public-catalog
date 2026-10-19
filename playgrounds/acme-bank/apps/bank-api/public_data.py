"""What ACME Bank publishes to everyone: its branches and its exchange rates.

The rates and the branches are the same, by value, as in bank-mcp/public_data.py. The two apps are separate images, so
the numbers are written twice and both test suites check the same digests and cases.
"""
from datetime import date

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


def rate(base, quote):
    return round(EUR_RATES[quote] / EUR_RATES[base], 4)
