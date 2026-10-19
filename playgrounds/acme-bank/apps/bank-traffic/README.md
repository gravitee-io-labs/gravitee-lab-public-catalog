# bank-traffic

## What it is

A gentle trickle of realistic calls through the gateway, so that the logs, the dashboards and the authorization
decisions of the playground are never empty. It speaks as the people of the bank (Alice, Bob and Tina), as the bank's agent
(Ace), as a developer with an API key, and as two teams of the AI workspace, with the official `mcp`, `a2a-sdk` and
`openai` clients. It keeps no state: a restart starts it again from scratch.

Every call carries `User-Agent: acme-bank-traffic`, for the apps' own logs. The Gamma Logs cannot filter on it: there,
what separates the generator from a person is the application. Its completions on the LLM proxy are the application
`ACME Bank traffic` (plan `Traffic`); its chats and tool calls are signed in with the Access Management application
`acme-bank-traffic` (the password grant, the same claims in the token as the web app's), which the web app does not use:
the people of the web app sign in at Access Management's own login page, with the authorization code flow.

## What it does

1. **Waits for the platform**, by asking it. The generator never depends on the order the containers start in or on a
   file the seed writes. Four things must be true, each checked with a small free request, again after 5 s, 10 s,
   20 s, 40 s, then every minute, and the log says which one it waits for:
   - `llm`: the LLM proxy answers `GET /models` with the `Traffic` key;
   - `mcp`: a `tools/list` as Alice returns 7 tools while Tools by role is on, or 8 while it is off (AM signs her in, the
     plan accepts the token; with `PROTECTIONS=on` only 7), and a public tool is permitted (the authorization policies are
     loaded);
   - `a2a`: the A2A proxy serves Ace's card to Alice's token;
   - `workspace`: `ACME Bank Teams` exists, is deployed, and the keys of `team-care` and `team-fraud` are accepted.
2. **Warms up**: about 40 calls over about 3 minutes, a first pass over every scenario in a random order, then draws
   from the table.
3. **Trickles**: one scenario every 2 minutes (30 an hour), 25% earlier or later, scaled by `TRAFFIC_RATE`.
4. **Judges each scenario** against the behavior matrix (who may do what with the bank's tools) and logs one line:
   `scenario=bob-reads-alices-accounts outcome=ok ms=2190 tokens=1630`. A failure is a warning and says why.
5. **Never stops**: a scenario that fails, raises or hangs is counted and the loop goes on. A scenario that meets a
   platform that does not answer three times in a row puts what it needs back on the waiting list (asked again every
   minute) while the traffic that does not need it continues.

An outcome is `ok`, `failed` (not what the matrix says, or the platform did not answer: look at it),
`inconclusive` (the small local model did not call the tool the scenario is about: it says nothing of the platform) or
`skipped` (a budget or a limit did not allow it). When Ace itself could not reach what it needs (its model, its token
exchange at AM, or its session with the bank's tools), the chat is `failed` with the reason of that hop, not
`inconclusive`: otherwise a broken path through Ace would never turn red.

### Money

Every transfer is followed by the opposite one, made by the owner of the account that received it with their own
token, so the balances of the story end where they started. The money Ace moves is read from its trace, whatever the
model decided to send. What cannot be given back at once (a limit, a restart) stays owed, is tried again after every
scenario, and no new transfer starts before it is settled.

A call can move money and still end with no answer (the gateway gives up after 30 s while Ace carries on, or the
scenario is cut after 150 s). Neither the trace nor a reply says so, so a scenario that may move money is watched: the
balances of the three accounts of the cast (Alice's two and Bob's one, read by their owners) are read before it, and
when it ends in an error or is cut they are read again. What moved from one account to another, and the scenario did
not note, is owed like any other transfer and given back. A give-back that gets no answer is not sent again blindly:
the balance of the paying account is read before each attempt and says whether the money already left. Balances that
moved in a way no single transfer explains, or that could not be read afterwards, are not touched: they are logged and
listed in `transfers.unexplained` of `/status` until the bank is started over. Two limits: a scenario that moved money while
a person did the same on those accounts in the same seconds cannot be told apart (pause the traffic for a live
demo), and a restart forgets what was owed.

Nothing here freezes `CARD-1001` or `CARD-2001`: the cards and accounts of the story are left alone, and the freeze
scenarios use the generator's own customer `C-9001` (`ACC-9001`, `CARD-9001`).

### Budgets

The generator shares the gateway with a person giving a demo, so it takes at most **40%** of any limit it meets (a
workspace budget moves its users to the small model at 50%). A ledger adds up what it spent in the last window of
each limit, and a scenario that would pass 40% is skipped. Where an answer carries the gateway's own count
(`X-Token-Rate-Limit-*`, `X-Cost-Rate-Limit-*`) that count is a floor, because a person may spend from the same
budget; a 429 leaves the limit alone until its window says it is over.

| Limit | Plan or budget | Window | The traffic keeps to |
|---|---|---|---|
| `ace` | LLM plan `Ace agent`: 1,000,000 tokens | hour | 400,000 tokens |
| `traffic` | LLM plan `Traffic`: 3,000 tokens | minute | 1,200 tokens |
| `team-care` | workspace budget `Customer care`: USD 5.00 | day | USD 2.00 |
| `team-fraud` | workspace budget `Fraud analytics`: USD 2.00 | day | USD 0.80 |

At `TRAFFIC_RATE=1` the table spends, on average:

- about 15 chats with Ace an hour (fewer than 20), of which 14 reach the model: about 31,000 tokens an hour, 3% of the
  Ace plan, a chat being 2,000 to 2,500 tokens (3,300 when the loop has to nudge the model);
- 1.5 completions an hour on the `Traffic` key, 250 tokens at most each, far below its 1,200 tokens a minute;
- 37 calls a day as `team-care` (USD 0.29, 6% of its day) and 24 as `team-fraud` (USD 0.20, 10% of its day), at the demo
  prices of 50 dollars per million tokens.

A higher rate sends more of the same, never above the caps: the ledger skips what would pass them. `team-hackathon` is
never used: its small hourly budget is the lesson of the guide.

## Scenarios

The weights are in `scenarios.py`. Tool calls are judged on Ace's trace (a model that did not call the tool is
`inconclusive`); calls made with a person's own token have exact outcomes and cost nothing.

**The protections the lessons switch on** (PII filtering, the prompt guard rails, Tools by role, Fine-Grained
Authorization, the cap on agents) start switched off, and the person switches them on one by one. The generator is told
which way the playground started by `PROTECTIONS`, the same setting as `ACME_BANK_PROTECTIONS` (`off` by default).

- **`off`**: a scenario that a protection decides accepts both answers: a denial or, while it is off, the call going
  through (or the bank refusing it itself). The same holds for an injection (blocked, or answered by the model), an IBAN
  in an answer and the tool list of a customer (7 tools or 8). What went through is not a failure and what moved is given
  back like any other transfer, and its line in the log says so (`detail=alice list_accounts went through: the control that
  decides it is off`), so that a reader can tell it from a denial; Gamma says which protections are on.
  What no protection decides stays strict: a call that must be permitted and is denied, a missing token (401), a guard that stops an ordinary question.
- **`on`**: everything is protected from the start (a presenter's mode), so the generator is strict again: a call that
  must be denied is denied (a permit, or the bank refusing it itself, is a failure), an injection is blocked before the
  model, the IBAN is not in the answer, a customer lists 7 tools and the platform is not ready while she lists 8. A
  policy that stopped working is then reported at the next scenario, not accepted.

The scenarios that can move money while the policy engine is off (`tina-sends-nothing`, `alice-sends-12000`, and the
others marked below) are watched like the transfers: the balances are read around them, and what moved is given back.

| Scenario | Who | Expected |
|---|---|---|
| `alice-accounts`, `alice-transactions`, `bob-balance` | chat with Ace | the tool is permitted for their own accounts |
| `alice-sends-120` | chat with Ace | permitted, then given back |
| `alice-sends-600-through-ace` | chat with Ace | `transfer_funds` denied: an agent moves at most EUR 500 (or permitted, and given back, while the cap is not deployed) |
| `bob-reads-alices-accounts` | chat with Ace | `list_accounts(C-1001)` denied (or permitted while Fine-Grained Authorization is off) |
| `tina-reads-alices-accounts` | chat with Ace | permitted: a teller helps every customer |
| `tina-freezes-the-test-card` | chat with Ace | `freeze_card(CARD-9001)` permitted |
| `public-tool-chat` | chat with Ace | exchange rate, loan or branches: permitted for anyone signed in |
| `injection-through-ace` | chat with Ace | blocked by the guard rails before the model (or answered by it while they are off; never with `PROTECTIONS=on`) |
| `alice-gives-an-iban` | chat with Ace | answered; the IBAN is not in the answer while PII filtering is on (never in it with `PROTECTIONS=on`) |
| `alice-reads-her-accounts`, `tina-reads-every-account`, `public-tools` | own token | permitted |
| `alice-reads-bobs-accounts`, `bob-lists-alices-accounts` | own token | 403 (or permitted while Fine-Grained Authorization is off) |
| `alice-freezes-nothing`, `tina-sends-nothing`, `alice-sends-12000` | own token | 403 (customers do not freeze, tellers do not move money, nobody sends above EUR 10,000), or permitted while Fine-Grained Authorization is off (the last two may move money: watched) |
| `alice-sends-zero-and-less` | own token | 403 for an amount of 0 and of -5 (or the bank's own refusal while Fine-Grained Authorization is off) |
| `alice-hides-bobs-account-behind-her-own` | own token | 403 for a transfer out of Bob's account with an extra `account_id` of her own: the policy reads the argument the tool reads |
| `tina-freezes-the-test-card-herself` | own token | permitted |
| `alice-sends-600-herself` | own token | permitted (the human path), then given back |
| `a-call-without-a-token` | none | 401 at the gateway |
| `who-sees-which-tools` | own token | `freeze_card` is in Tina's `tools/list`, and in Alice's only while Tools by role is off (never with `PROTECTIONS=on`) |
| `faq-on-the-traffic-key` | `Traffic` key | answered; the log says when the answer came from the cache |
| `injection-on-the-traffic-key` | `Traffic` key | 400 from the guard rails, or an answer while they are off (the 400 only, with `PROTECTIONS=on`) |
| `customer-care-asks`, `fraud-analytics-asks` | workspace keys | answered, with the budget headers |

## Log

One line per scenario, a warning when it fails, a line when money comes back:

```
17:49:08 INFO bank-traffic scenario=alice-sends-600-herself outcome=ok ms=14 tokens=0
17:49:08 INFO bank-traffic gave back 600 EUR to ACC-1001
17:49:09 INFO bank-traffic scenario=alice-sends-600-through-ace outcome=ok ms=7 tokens=1600
17:49:12 INFO bank-traffic scenario=faq-on-the-traffic-key outcome=ok ms=3 tokens=0 detail=answered from the cache
17:51:14 WARNING bank-traffic scenario=bob-reads-alices-accounts outcome=failed ms=902 tokens=1634 detail=list_accounts came back ok (done), expected it denied
```

## What it relies on

- **bank-mcp**: its eight tools with their arguments, and the customer `C-9001` with `ACC-9001` and `CARD-9001`.
- **bank-agent**: the answer of Ace is a text part and a data part `{"trace": [...]}`, a row per hop with `step`
  (`llm`, `exchange`, `tool`), `name`, `arguments`, `outcome` (`ok`, `denied`, `blocked`, `rate_limited`, `error`),
  `detail` and `status`. The tokens of a model call are read from `detail` ("1,534 tokens, ...") or a `tokens` field,
  else guessed at 900. A row with a status from 500, an `llm` or `exchange` row with the outcome `error`, and the
  `tool` row named `connect` with the outcome `error` or `denied` (the session with the bank's tools did not open) say
  that the platform did not answer: the chat is `failed`. A `connect` row that is `rate_limited` is a skip.
- **The seed**: the three proxies and their plans, the AI workspace `ACME Bank Teams` with the users `team-care` and
  `team-fraud`, and the APIM application `ACME Bank traffic`, which has the client id of the generator and is
  subscribed to the A2A plan. The cache conditions of the LLM proxy name the `Developers` and the `Traffic` plans, and
  `faq-on-the-traffic-key` relies on the `Traffic` one: take that plan out of them and its repeated question is never
  answered from the cache.

## Endpoints

The control port is `HTTP_PORT` (8000), inside the playground's network, with no sign-in.

| Call | What it does |
|---|---|
| `GET /health` | `{"status": "ok"}` as soon as the process is up, whatever the platform does |
| `GET /status` | the state (`waiting`, `warming-up`, `running`, `paused`), what it waits for, the warm-up, the counters of each scenario with the last outcome, the ledger (used, cap and percent of each limit), the money moved, returned, owed and unexplained |
| `POST /pause` | no new scenario starts; the one in progress ends first |
| `POST /resume` | goes on |
| `POST /reset` | the counters start again and nothing is owed or unexplained (the bank is reset with them). The ledger stays: the gateway's windows go on counting what was spent |

## Environment

| Variable | Meaning | Default |
|---|---|---|
| `GATEWAY_URL` | the gateway as this container reaches it; the AI workspace is served under it | `http://apim-gateway:8082` |
| `LLM_URL` | the LLM proxy | `$GATEWAY_URL/acme-bank/llm` |
| `MCP_URL` | the MCP proxy, without a trailing slash | `$GATEWAY_URL/acme-bank/mcp` |
| `ACE_URL` | the A2A proxy | `$GATEWAY_URL/acme-bank/ace/` |
| `AM_TOKEN_URL` | AM's token endpoint, for the password grant | `http://am-gateway:8092/acme-bank/oauth/token` |
| `TRAFFIC_CLIENT_ID` | the AM application of the generator (type WEB, the password grant), whose APIM application is subscribed to the A2A plan | `acme-bank-traffic` |
| `TRAFFIC_CLIENT_SECRET` | its secret | none: required |
| `BANK_DEMO_PASSWORD` | the password of Alice, Bob and Tina | none: required |
| `TRAFFIC_LLM_API_KEY` | the key of the LLM plan `Traffic` | none: required |
| `APIM_MANAGEMENT_URL` | the management API, for the platform users | `http://apim-management-api:8083` |
| `AIM_GAMMA_URL` | where `/gamma` is served; another host when the platform serves it elsewhere | `$APIM_MANAGEMENT_URL` |
| `APIM_ORG`, `APIM_ENV` | organization and environment | `DEFAULT` |
| `APIM_TOKEN`, or `APIM_USERNAME` and `APIM_PASSWORD` | credentials of the management API, as the seed has them | none: one of the two is required |
| `WORKSPACE_NAME` | the AI workspace of the teams | `ACME Bank Teams` |
| `PROTECTIONS` | `on` when the playground starts with its lessons' protections on: the generator then expects a denial, a block, a masked IBAN and 7 tools; `off` accepts both outcomes (compose passes `ACME_BANK_PROTECTIONS`) | `off` |
| `TRAFFIC` | `off` starts paused, until `POST /resume` | `on` |
| `TRAFFIC_RATE` | 1 is one scenario every 2 minutes; from 0.1 to 10 | `1` |
| `HTTP_PORT` | the control port | `8000` |

A missing secret stops the container with one line that names them all.

## Run

Compose starts it with the playground, with the addresses and the secrets it needs. On its own, give it the required
settings of the table above, for example in an env file:

```bash
docker build -q -t bank-traffic . && docker run --rm -p 127.0.0.1:8000:8000 --env-file traffic.env bank-traffic
```

## Tests

`make test-apps` from the repository root runs the tests of every app in its image. For this app alone, from this folder:

```bash
docker build -q -t bank-traffic-test . && docker run --rm --entrypoint python bank-traffic-test -m unittest discover -s tests -t .
```

Without Docker, in a Python 3.14 virtual environment with the pins of `requirements.txt`:
`python -m unittest discover -s tests -t .` from this folder.

They run against a fake platform in memory (AM, the three proxies, the AI workspace, Gamma and Ace behind the real
SDKs), with no socket.
