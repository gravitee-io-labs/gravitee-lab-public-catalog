# bank-mcp

## What it is

The MCP server of ACME Bank: accounts, cards, transfers and public banking information, as tools an AI agent can
call. It is built with the official `mcp` SDK, keeps its data in memory and has **no authentication** on MCP: the
playground puts the Gravitee gateway in front of it, and publishes its own port to show what an unprotected server
allows. The one route that is not MCP, `POST /admin/reset`, asks for a token (see Admin route).

- MCP over Streamable HTTP at `/` (stateless, JSON answers), protocol versions 2026-07-28 and 2025-11-25
- `GET /health` answers `{"status": "ok"}`
- `POST /admin/reset` puts the data back to its start (see Data), for whoever sends the `X-Admin-Token` header
- Server name `ACME Bank MCP`: the catalog derives the slug `acme-bank-mcp` from it, and every authorization id
  (`MCPServer::acme-bank-mcp`, `acme-bank-mcp.<tool>`) from the slug. Renaming the server renames them all.

## Tools

| Tool | Arguments | What it does |
|---|---|---|
| `list_accounts` | `customer_id` | Accounts of a customer with type, currency and balance |
| `get_balance` | `account_id` | Balance of one account |
| `list_transactions` | `account_id`, `limit` (10), `category` | Latest transactions, newest first, with `count` and `total` of the rows returned |
| `transfer_funds` | `from_account`, `to_account`, `amount`, `reference` | Moves EUR between two accounts and returns a confirmation id |
| `freeze_card` | `card_id`, `reason` | Freezes a card; freezing a frozen card is not an error |
| `get_exchange_rate` | `base` (the currency the amount is in), `quote`, `amount` | Rate between two of EUR, USD, GBP, CHF, JPY, CAD, SEK, and `converted`: the `amount` in `base` as an amount in `quote`, to two decimals (1 for the plain rate) |
| `simulate_loan` | `amount`, `years`, `annual_rate_percent` (4.2) | Monthly payment and total cost |
| `find_branches` | `city` | Branches of a city with address and opening hours |

Prompts: `summarize_spending(account_id, month)`, `dispute_charge(transaction_id)`.
Resources: `acme://policies/fees` and `acme://policies/card-security`, in Markdown. Their text, `policies.py`, is
also what the playground's two knowledge documents say, character for character: a test of the seeder compares them,
so a change goes into all three.

The tool descriptions are tuned: they say what a small local model needs to pick the right tool and to fill its
arguments (a default it cannot see, how to name a currency pair, when to call `list_accounts` first). They give an id
as an example (`ACC-1001`) and leave the id arguments without a description of their own in the schema: a model given
the id format alone, or a schema that describes each id, asks the customer which account they meant instead of calling
a tool. The tests pin the text the model reads. After a change, chat the guide's example questions with Ace and the
guard rails on, then take the new digests.

**Money arguments are strict**: `amount` must be a JSON number above zero. `"12000"` is refused, where the SDK would
otherwise read it as 12000.0 while a gateway rule that reads the raw request sees a string. The server enforces funds,
never limits: the limits (EUR 10,000 for anyone, EUR 500 for an agent acting for a customer) belong to the gateway.

**The exchange tool does the sum.** A small model that is given only a rate multiplies it badly, so
`get_exchange_rate` takes the amount and answers `converted`. The amount is required (1 for the plain rate): a model
leaves an optional argument out. For 2,500 EUR in USD the answer is:

```json
{"base": "EUR", "quote": "USD", "rate": 1.0842, "converted": 2710.5, "date": "2026-10-01"}
```

It converts with the exact rate, not the one rounded to four decimals that it shows. The gateway's policies judge an
`amount` only for `transfer_funds`, so this tool changes no decision.

## Who may reach it by which name

The MCP endpoint asks no one who they are, so the published port must not be usable from a web page: a page on another
site that makes your browser call `localhost:8111` is refused. A call needs a `Host` from `ALLOWED_HOSTS` (`421`
otherwise: the DNS rebinding trick, a hostile name that points at this machine, sends its own name), an `Origin` from
the same names when a browser sends one (`403`), and a JSON body (`400` for the plain text a page can send without
asking the browser's leave). The Compose file adds the service's own name, `bank-mcp`, which is how the gateway and the
other containers reach it; give your own host name in `ALLOWED_HOSTS` when the gateway reaches it by another. `/health`
and the admin route are not MCP: `/admin/reset` has its token.

## Admin route

`POST /admin/reset` is not MCP: it answers `403` unless the `X-Admin-Token` header equals `ADMIN_TOKEN`, and always when
the server has no token. The gateway's MCP proxy answers `404` to every path but its root (its first flow, `Only the MCP
endpoint`), so a signed-in customer cannot reach the route through it: the token is the lock for the published port and
for anything else that goes around the gateway. The bank's web app (bank-web) is the one that holds it. A refused call is
logged, without the token it carried.

## Data

The same at every start. Transaction dates are counted back from the day the container started, and each account has
12 to 15 transactions in groceries, rent, salary, transport, restaurants, subscriptions and utilities (the savings
account has interest and transfers).

| Customer | Accounts | Card | Opening balance (EUR) |
|---|---|---|---|
| `C-1001` Alice Martin | `ACC-1001` checking | `CARD-1001` | 4,820.55 |
| | `ACC-1002` savings | | 15,300.00 |
| `C-2001` Bob Chen | `ACC-2001` checking | `CARD-2001` | 920.10 |
| `C-9001` Traffic Test | `ACC-9001` checking | `CARD-9001` | 25,000.00 |

`C-9001` is not part of the story. It is there for the traffic generator, which freezes `CARD-9001` and moves money
to and from `ACC-9001` so the story's cards stay active and its balances stay where the guide says they are.

A transfer changes balances, not the transaction history. `POST /admin/reset` puts balances, cards and the
confirmation counter back; nothing else changes at runtime. The history is fixed data.

## Environment

| Variable | Meaning | Default |
|---|---|---|
| `HTTP_PORT` | Port the server listens on, on every interface | `8000` |
| `ALLOWED_HOSTS` | Names the server is reached by, comma separated, without port: the `Host` of a call, and the `Origin` of a browser's | `localhost,127.0.0.1,[::1]` |
| `ADMIN_TOKEN` | What `POST /admin/reset` asks for in `X-Admin-Token`; without it the route refuses every call | none |

## Run

```bash
docker build -q -t bank-mcp . && docker run --rm -p 127.0.0.1:8000:8000 bank-mcp   # MCP at http://localhost:8000/
```

The log has one line per MCP request, naming the tool, the prompt or the resource and how it went, never its arguments:
`tools/call get_balance -> ok in 1 ms (protocol 2026-07-28)`.

## Tests

`make test-apps` from the repository root runs the tests of every app in its image. For this app alone, from this folder:

```bash
docker build -q -t bank-mcp-test . && docker run --rm --entrypoint python bank-mcp-test -m unittest discover -s tests -t .
```

Without Docker, in a Python 3.14 virtual environment with the pins of `requirements.txt`:
`python -m unittest discover -s tests -t .` from this folder.
