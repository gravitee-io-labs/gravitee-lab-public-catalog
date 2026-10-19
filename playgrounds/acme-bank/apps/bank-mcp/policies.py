"""The two policy documents the server publishes as MCP resources.

They say what the platform enforces: the limits below are the ones its authorization policies apply.
"""

FEES = """\
# ACME Bank fee schedule

Fees for personal customers, in EUR.

| Service | Fee |
|---|---|
| Checking account | 2 per month |
| Savings account | free |
| Debit card | 12 per year |
| Replacement of a lost or stolen card | free |
| SEPA transfer | free |
| Transfer outside the euro area | 5 |
| Cash withdrawal at an ACME Bank ATM | free |
| Cash withdrawal at another bank's ATM in the euro area | free |
| Cash withdrawal outside the euro area | 3 |
| Card payment outside the euro area | 1% of the amount |

## Transfer limits

- A transfer cannot exceed EUR 10,000.
- An AI assistant acting for a customer, such as Ace, can send at most EUR 500 per transfer. Above that, the
  customer makes the transfer in the ACME Bank app or at a branch.
"""

CARD_SECURITY = """\
# ACME Bank card security policy

## A lost or stolen card

Tell ACME Bank at once. A teller freezes the card in seconds and a replacement is sent free of charge. A frozen
card refuses every payment and withdrawal. Only bank staff can freeze a card: the assistant does not offer it to
customers.

## Keeping a card safe

- Never share your PIN or the one-time codes you receive. ACME Bank staff never ask for them.
- Contactless payments are limited to EUR 50 each; the card asks for its PIN from time to time.
- An online payment above EUR 30 is confirmed in the ACME Bank app.

## A charge you do not recognize

Report it within 13 months. An unauthorized payment is refunded by the end of the next business day while the
dispute is investigated.
"""
