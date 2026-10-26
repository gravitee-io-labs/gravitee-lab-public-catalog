# bank-web

## What it is

ACME Bank's web app: one Starlette server with no database, and a page of plain HTML, CSS and JavaScript modules, with
no build step and nothing loaded from outside. People sign in at Access Management's own login page, ask Ace through the
gateway, and see every call an answer was made of, hop by hop, in **Behind the answer**. Beside the conversation sit
**commands**, ready-made questions and actions that the guide can press for the person; the app never judges what a
call proved, because the proof is read in Gamma.

| View | What |
|---|---|
| Assistant | The conversation with Ace, as one of three people. A switch chooses the route, **Direct** or **Through the Gravitee gateway**; **Send money** pays with the person's token, without Ace; **Tokens** shows the token and the one Ace got |
| Commands | The ready-made questions, grouped under the titles of the guide's lessons, with **Start the bank over** at the foot |
| Behind the answer | The call of the selected answer as a list of hops: a column from 1280 px, a sheet below |
| Teams | An AI workspace with the key of a team: short and long answers, the budget meter, the router's state |
| Developers | The LLM proxy with the Developers key: **Send**, **Send x10** (runs into the 429), **Ask the cached FAQ twice** |
| Presenter | **Check** (is everything ready), **Warm up**, **Pause traffic** / **Resume traffic**, **Start the bank over** |

The views have addresses, `#assistant`, `#teams`, `#developers` and `#presenter`, and `#commands` on a phone. Any other
address shows the Assistant.

## Run

Compose starts it with the playground, at `http://localhost:8110`. On its own it needs the two secrets, and most of the
page needs the platform behind it:

```bash
docker build -q -t bank-web . && docker run --rm -p 127.0.0.1:8110:8000 \
  -e WEB_CLIENT_SECRET=<secret> -e BANK_DEMO_PASSWORD=<password> bank-web
```

## Environment

The two secrets are required; every address has the lab's. A missing secret or a `HTTP_PORT` that is not a number stops
the container with one line that says which.

| Variable | Meaning | Default |
|---|---|---|
| `WEB_CLIENT_SECRET` | Secret of the AM application `acme-bank-web`, which the server exchanges the code with | required |
| `BANK_DEMO_PASSWORD` | Password of the three users; the menu of who is asking shows it, the app signs nobody in with it | required |
| `ADMIN_TOKEN` | What **Start the bank over** sends to the bank's MCP server in `X-Admin-Token`; empty, the reset is refused | empty |
| `WEB_CLIENT_ID` | Client id of that application | `acme-bank-web` |
| `AM_TOKEN_URL` | Token endpoint of the AM domain, as this container reaches it | `http://am-gateway:8092/acme-bank/oauth/token` |
| `AM_AUTHORIZE_URL` | Authorize endpoint of the AM domain, as the browser reaches it | `http://localhost:8092/acme-bank/oauth/authorize` |
| `ACE_URL` | Ace through the gateway (the A2A proxy) | `http://apim-gateway:8082/acme-bank/ace/` |
| `ACE_DIRECT_URL` | Ace with no gateway | `http://bank-agent-direct:8000/` |
| `MCP_URL` | The MCP proxy, without a trailing slash | `http://apim-gateway:8082/acme-bank/mcp` |
| `MCP_DIRECT_URL` | The bank's MCP server itself; its origin serves `/admin/reset` | `http://bank-mcp:8000/` |
| `LLM_URL` | The LLM proxy (`/chat/completions` is added) | `http://apim-gateway:8082/acme-bank/llm` |
| `DEV_LLM_API_KEY` | Key of the Developers plan | empty: the Developers view says so |
| `GATEWAY_URL` | The gateway; an AI workspace is `GATEWAY_URL` plus its path | `http://apim-gateway:8082` |
| `APIM_MANAGEMENT_URL`, `APIM_ORG`, `APIM_ENV` | The management API, which also serves Gamma | `http://apim-management-api:8083`, `DEFAULT`, `DEFAULT` |
| `APIM_USERNAME` and `APIM_PASSWORD`, or `APIM_TOKEN` | Credentials to read the team keys, Agent Identity, the analytics, and the logs and traces of the evidence | empty |
| `GAMMA_URL` | The Gamma console as the browser reaches it, for the links | `http://localhost:8086` |
| `TRAFFIC_URL` | Control port of bank-traffic | `http://bank-traffic:8000` |
| `ALLOWED_HOSTS` | Host names the page may be reached by, comma separated, without port | `localhost,127.0.0.1,[::1]` |
| `HTTP_PORT` | Port to listen on | `8000` |

## What it expects of the other services

- **Access Management** serves the authorize and token endpoints (authorization code with PKCE `S256`, and
  `refresh_token`) to the application `acme-bank-web`: type WEB, PKCE enforced, consent skipped, the redirect URIs
  `http://localhost:8110/callback` and `http://127.0.0.1:8110/callback` (the page sends the browser back to the address
  it came from). Its tokens carry the `username` claim.
- **Ace** answers an A2A `SendMessage` with a text part and a data part, `{trace, tools, delegated_claims}`. Each row of
  the trace is one call Ace made, in order, and carries the gateway's `request_id` of that call, which the evidence is
  found by. The call that brought the question has no row: its id is the `x-gravitee-request-id` header of the gateway's
  answer.
- **The bank's MCP server** answers `tools/list` and `tools/call` over plain JSON-RPC, and `POST /admin/reset` when
  `X-Admin-Token` is its own `ADMIN_TOKEN` (`ACME_BANK_ADMIN_TOKEN` in the playground's settings). **bank-traffic** answers `GET /status`
  (`paused` among its fields), `POST /pause`, `POST /resume` and `POST /reset`.
- **The management API** serves the AI workspaces and their users' keys, the APIs by name, the logs, traces and
  decisions of the evidence, the dashboards and analytics, and Agent Identity. It is never asked what a protection is
  set to.

## API

All JSON, same origin, no CORS.

| Route | |
|---|---|
| `GET /health` | `{"status": "ok"}` |
| `GET /login?persona` | Starts a sign-in: `302` to Access Management's login page; `400` unless the person is one of the three |
| `GET /callback?code&state` | Finishes the sign-in and `303`s to `/sign-in-done.html?outcome=signed-in\|refused\|expired\|other\|stranger\|failed` |
| `GET /api/config`, `GET /api/personas` | The Gamma address and the console's pages; the three users with their demo user name and password |
| `GET /api/session`, `POST /api/session {persona}`, `DELETE /api/session` | Who asks and who is signed in; ask as another person who is signed in; sign out |
| `GET /api/tokens`, `POST /api/token` | The claims of the user token and of the token Ace got; the user's own token (a POST, so only this page asks) |
| `GET /api/commands`, `POST /api/commands/{id}/run` | The commands; run one that asks Ace or pays |
| `POST /api/chat {message, gateway: on\|off}` | The answer, its hops (`rows`), and `who` answered |
| `POST /api/send-money {from_account, to_account, amount, reference?, gateway?}` | The payment, which is one hop, with `who` |
| `POST /api/dev/llm {message, variation?}` or `{faq: true}` | One answer of the LLM proxy, with the `question` |
| `GET /api/teams`, `POST /api/teams/chat {team, kind: short\|long, since?}` | The teams; one answer of the workspace (`since`: when its run began, in ms) |
| `GET /api/evidence?kind&api&request&at&since?` | The item of a call in Gamma; see "Evidence" |
| `GET /api/presenter/check`, `POST /api/presenter/warmup`, `POST /api/presenter/reset` | The Presenter view; the reset is "Start the bank over" |
| `GET /api/presenter/traffic`, `POST /api/presenter/traffic {action: pause\|resume}` | The traffic generator |

An answer is `{answer, gateway, protected, ms, rows, delegated_claims, who}`; `rows` are the hops (`hops.py`,
`answers.py`). A call that failed is `{error, who, rows?}`: `who` is who asks now and who is signed in, as the call left
them, and `rows` holds the one hop of the call when the gateway answered it (a 401, a 504).

### Commands

A command asks as the person it is for, with that person's token if this browser holds one, and with none if it does
not: the gateway's `401` is then the answer, with its hop. A command never signs anybody in; that is the person
control's job. Its id is what a guide names in an action link, `[Leak an IBAN](action:leak-an-iban)`, and does not
change with the label.

| # | Group | Command (`id`) | As | Runs |
|---|---|---|---|---|
| 1 | See everything | **Ask Ace about my accounts** (`ask-ace-accounts`) | Alice | The question through the gateway: the `401` with nobody signed in |
| 1 | See everything | **Ask Ace without the gateway** (`ask-ace-direct`) | Alice | The same question, direct |
| 2 | Protect the model | **Leak an IBAN** (`leak-an-iban`) | Alice | A question with an IBAN in it |
| 2 | Protect the model | **Inject a prompt** (`inject-a-prompt`) | Alice | A prompt injection |
| 3 | Protect the tools | **Freeze a card as a customer** (`freeze-card-customer`) | Alice | Freezing a card, as its owner |
| 3 | Protect the tools | **Freeze a card as a teller** (`freeze-card-teller`) | Tina | Freezing the same card, as a teller |
| 4 | Decide who may do what | **Read another customer's accounts** (`read-other-accounts`) | Bob | Asking for another customer's accounts |
| 5 | Cap what an agent may do | **Move EUR 600 through Ace** (`move-600-through-ace`) | Alice | The transfer, asked of Ace |
| 5 | Cap what an agent may do | **Move EUR 600 yourself** (`move-600-yourself`) | Alice | The transfer, as the form's payment with no agent |
| 6 | Cap what teams spend | **Spend the Hackathon budget** (`spend-hackathon-budget`) | | Up to four long answers of the Hackathon team, in Teams |

`POST /api/commands/{id}/run` answers like `/api/chat` or `/api/send-money`. With no token for the person, a question
through the gateway answers the gateway's refusal, `{error, who, rows}` with a `401`; a payment is a receipt that did
not move; the command that goes direct has no gateway to refuse it, so the answer is the app's own `401`. The budget
command is run by the page through `/api/teams/chat`, answer by answer. To add a command, add it to its group in
`commands.py`, name it in the guide, list its id above, and test it in `tests/test_commands.py`.

### Messages with the Lab UI

The page knows two modes, standalone in a tab of its own and framed by the Lab UI. **The Lab UI must be served on port
9000**: only `http://localhost:9000` and `http://127.0.0.1:9000` may frame the page or be heard by it (`LAB_UI` in
`security.py`, `LAB_ORIGINS` in `static/js/embed.js`).

| Message | From | To | |
|---|---|---|---|
| `{type: "gravitee-lab:action", id}` | the Lab UI | the page | Run the command of that id, as its button does |
| `{type: "gravitee-lab:ready"}` | the page | the Lab UI | The page listens and has its commands |
| `{type: "gravitee-lab:open", url}` | the page | the Lab UI | Show this address of Gamma in the Lab UI's own tab |

- The page listens only when framed, and acts on an action only if it comes from `window.parent`, from one of the two
  origins, with an `id` of the shape `[a-z0-9][a-z0-9-]{0,63}`. It posts to the origin the browser says the parent has,
  else to each of the two, never to `*`.
- Framed, the Commands start as a slim strip and the page adds no entry to the session history; standalone the Commands
  start open. A choice of the person is kept in the browser, one for each mode.

### Behind the answer

Every hop is one call that made the answer, in the same four parts: a **title** from the table below (`hops.py`; the
page, the guide and this file use no other words); three **badges**, the system the call went through (or **No
gateway**), its status and its duration; one **line** that says what happened; and the **evidence** of that call, in the
order Trace, Logs, Decisions, Spend. What a call held (arguments, results, tokens) is behind one **Details**.

| Kind of hop | Title | System | Evidence |
|---|---|---|---|
| The call that brought the question | `<Person> asked Ace`; `Someone not signed in asked Ace` when no token was sent | A2A proxy | Trace, Logs |
| The token exchange (RFC 8693) | `Ace got a token for <Person>` | Access Management | none |
| The list of tools | `Ace asked which tools it may use` | MCP proxy | Trace, Logs |
| The model, the first time | `Ace asked the model what to do` | LLM proxy | Trace, Logs |
| The model, again before a tool has answered | `Ace asked the model again` | LLM proxy | Trace, Logs |
| The model, after a tool has answered | `Ace asked the model for the answer` | LLM proxy | Trace, Logs |
| A tool Ace called | `Ace called <tool>` | MCP proxy | Trace, Logs, Decisions |
| A tool the person called (**Send money**) | `<Person> called transfer_funds`; `Someone not signed in called transfer_funds` | MCP proxy | Trace, Logs, Decisions (Trace and Logs when the OAuth2 plan refused it) |
| A team's call | `<Team> asked the AI workspace` | AI workspace | Trace, Logs, Spend |
| A developer's call | `A developer asked the model` | LLM proxy | Trace, Logs |
| Anything Ace could not finish | `Ace could not finish` | | none |

### Evidence

Each button opens the item of its call, not a list: the trace, the log entry, the decision of the policy engine, or the
dashboard of what a run spent. Gamma writes an item some seconds after the call, so `GET /api/evidence` finds it when
the button is pressed: `kind` is `trace`, `logs`, `decisions` or `spend`, `api` is `a2a`, `llm`, `mcp` or `teams`,
`request` is the gateway's id of the call, `at` is when the link was made (ms) and `since` is when a run began. Anything
else is a `400`, and nothing is asked of the platform for it. With `resolve=1` it looks once and answers `{state,
url?}`: `found` (`url` is the item), `pending` (not there yet, for 25 s after the call and 15 for a decision: whoever
follows asks again), `missing` (Gamma has none: `url` is the list of its kind, around the time of the call) or `down`
(the platform does not answer: nothing opens). Without it, a link followed in a tab, it answers `follow.html` at once
and holds no connection. `url` is always built from ids that were checked, never from what the platform says.

Gamma has to be signed in first, because its sign-in drops the query of a **Logs** or **Decisions** link; the guide has
the person sign in and press the button again.

## Security

- The browser holds an opaque id in an HttpOnly, SameSite=Lax cookie (Lax, because a sign-in comes back from Access
  Management with a navigation of another site). The tokens stay in the server's memory: 8 hours, 200 sessions at most,
  renewed with the refresh token; a refresh that Access Management refuses ends the sign-in. The one place a token
  leaves is the Tokens drawer, which shows the signed-in user their own token: fetched when it opens, emptied when it
  closes, never logged.
- The sign-in is the authorization code flow with PKCE (S256). The server keeps the `code_verifier` and the `state`; a
  sign-in belongs to the browser session that started it and is taken once; the code is exchanged by the server, with
  the client secret; the person read from the token must be the person asked for. The window then goes (`303`) to
  `/sign-in-done.html?outcome=...`, so no code, state or token is in an address, a page or a log; that page tells its
  opener how it ended, to its own origin only, and the page then asks the server who is signed in.
- The Developers key and the keys of the teams never leave the server.
- Every request but `/health` needs a `Host` from `ALLOWED_HOSTS`. Every request that changes something, and every `GET`
  of an `/api` route, must come from this page: its `Origin` is this `Host`, or it is not marked cross-site
  (`Sec-Fetch-Site`), and a `GET` also carries `X-Requested-With: acme-bank` (`curl` needs `-H 'X-Requested-With:
  acme-bank'`). `/api/evidence` is opened by a link, which cannot carry a header, so it has the `Origin` and
  `Sec-Fetch-Site` rules only.
- The page is served with a content security policy that allows nothing but itself, and only the Lab UI may frame it.
  Everything a server says is shown with `textContent` or as built nodes, never as markup.
- Logs: one INFO line per request or step, naming the user, the hops and their outcome. Never a question, an argument, a
  token or a key.

## Tests

`make test-apps` from the repository root runs the tests of every app in its image. For this app alone, from this
folder:

```bash
docker build -q -t bank-web-test . && docker run --rm --entrypoint python bank-web-test -m unittest discover -s tests -t .
```

Add `-v <playground>/guide.md:/guide.md:ro -e GUIDE=/guide.md` to run the checks of the guide too; without it they are
skipped. Without Docker, in a Python 3.15 virtual environment with the pins of `requirements.txt`: `python -m unittest
discover -s tests -t .` from this folder. The tests run the real app over in-memory fakes of Access Management, the
gateway, the bank's MCP server, the management API and the traffic generator (`tests/fakes.py`).

The JavaScript of the page is tested with `node:test` in `tests/js`, over a small DOM of its own: `make test-apps` runs
it too, and on the host `node --test "tests/js/*.test.mjs"` does with a current Node.

## Working on the page

`static/README.md` holds the file map of the page, the rules of its look, and how to see it without a platform.
