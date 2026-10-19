"""The system prompt of Ace, built from the claims of the user's token.

Short and plain on purpose: a routing table says which tool answers which kind of request, which a small model that
does not think uses as a lookup. The gateway's guard rails score the system prompt together with the user's message, so
it holds no "never reveal" or "ignore" phrase, and a sentence added to it can flip every call into a block: after any
change, chat the guide's example questions with the guard rails on.

The user is named by name, customer id and accounts, never by email address: personal data the prompt does not need.
The accounts are what lets a question about "my" account name the right one: without them the model copies the example
id of the tool descriptions, and Bob's own question reads Alice's account. They go in the parenthesis of the name:
written as a sentence or a line of their own ("Their accounts are ...") they push the model to answer "What is the
balance of ACC-2001?" with list_accounts instead of get_balance. A directory of the bank's customers is left out on
purpose: it makes the model say from the prompt that an account "is not known", so Ace stops asking the bank and the
gateway never gets to say no. Who owns an account is for the bank to know, not the agent.

For the same reason a question that names an account is asked without the user's accounts. With them the model reads
"the balance of ACC-2001" next to "accounts ACC-1001, ACC-1002", answers that the account is not available and lists
the user's own accounts instead, so the gateway's policy is never asked about the account that was named. Without them
the model calls get_balance with the id it was given. The question that names no account ("from my savings to my
checking account") keeps them: without them the model invents an id ("SAV-1001") for the account it is told by type.
"whoever it belongs to" on the line for an account id is for "what Alice has in ACC-1002" asked by Bob: without it the
model lists Bob's own accounts with an extra argument, and the gateway is never asked about ACC-1002.

The line for accounts names the customer's own id, not "the customer id". The gateway masks an email address, a phone
number, an IBAN or a card number in what the user types, and a model that reads "My email is [REDACTED], show my
accounts" writes "[REDACTED]" as the customer id: the bank says no and the user hears "not allowed". That holds only
when the question names no account. Where it names one, the spelled-out id sends "What is my balance on ACC-2001?" to
list_accounts instead of get_balance, which is what the web app's commands, the traffic generator and the guide expect.

The line for the exchange rate asks for the amount: given only a rate the model does the multiplication itself and gets
it wrong, so the tool converts. The amount is a required argument (1 for the plain rate, said in the tool, not here): a
model leaves an optional one out, and "(1 for the plain rate)" in this prompt makes the guard rails block "Show my
accounts and balances" as malicious.
"""
import re
from typing import Any

ANONYMOUS = "a user of the bank"
MAX_ACCOUNTS = 5
NAMED_ACCOUNT = re.compile(r"\bACC-\d+", re.IGNORECASE)      # an account id in the question
TELLER = "{name}, a teller (bank staff). Tellers may look at any customer's accounts and freeze cards"

ANY_ID = "the customer id"
OWN_ID = "customer_id {customer_id}, whatever else the user says about themselves"
ROUTING = (
    "You act by calling tools, never by describing them. Which tool to call:\n"
    "- balance, \"how much do I have\", accounts: list_accounts with {id} "
    "(never ask the user for an account id)\n"
    "- one account whose id is given (ACC-1001), whoever it belongs to: get_balance or list_transactions with that id\n"
    "- transactions, spending, groceries, rent: list_transactions\n"
    "- send, move, transfer money: transfer_funds, only when the amount and both accounts are known\n"
    "- exchange rate, currency conversion: get_exchange_rate, with the amount to convert\n"
    "- loan, mortgage, monthly payment: simulate_loan\n"
    "- branch, agency, opening hours: find_branches\n"
    "- freeze a card: freeze_card\n"
    "For a greeting, a general question or a request that lacks details, answer in text and ask for what is missing. "
    "Do not invent numbers, ids or dates.\n"
    "If a tool answers that the action is not allowed, say so plainly in one sentence. "
    "You do not give investment advice. Answer briefly, in the language of the user."
)


def text(value: Any) -> str:
    """A claim as one short line: it ends up in a prompt."""
    return " ".join(str(value).split())[:80] if isinstance(value, (str, int)) else ""


def who(claims: dict[str, Any]) -> str:
    name = text(claims.get("name")) or ANONYMOUS
    if claims.get("role") == "teller":
        return TELLER.format(name=name)
    details = []
    if customer_id := text(claims.get("customer_id")):
        details.append(f"customer id {customer_id}")
    if accounts := accounts_of(claims):
        details.append(f"accounts {', '.join(accounts)}")
    return f"the customer {name} ({', '.join(details)})" if details else name


def accounts_of(claims: dict[str, Any]) -> list[str]:
    accounts = claims.get("accounts")
    return [a for a in map(text, accounts[:MAX_ACCOUNTS]) if a] if isinstance(accounts, list) else []


def routing(claims: dict[str, Any], question: str = "") -> str:
    """The routing table. A customer's own id is spelled out on the line for accounts, unless the question names an
    account; a teller names the customer."""
    named = NAMED_ACCOUNT.search(question)
    customer_id = "" if claims.get("role") == "teller" or named else text(claims.get("customer_id"))
    return ROUTING.format(id=OWN_ID.format(customer_id=customer_id) if customer_id else ANY_ID)


def build_system(claims: dict[str, Any], question: str = "") -> str:
    if NAMED_ACCOUNT.search(question):
        claims = {key: value for key, value in claims.items() if key != "accounts"}
    return f"You are Ace, the assistant of ACME Bank. You are talking to {who(claims)}.\n{routing(claims, question)}"
