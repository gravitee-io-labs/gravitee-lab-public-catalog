# bank-agent

## What it is

Ace is ACME Bank's AI assistant, an A2A 1.0 agent. A signed-in user (or a teller) asks in plain words; Ace asks a model,
the model asks the bank's tools (MCP), Ace answers. The same image runs twice:

| Service | Ace | Model | Tools | Acts as |
|---|---|---|---|---|
| `bank-agent` | behind the gateway | the gateway's LLM proxy, with Ace's API key | the gateway's MCP proxy | the user, through Ace (token exchange at AM) |
| `bank-agent-direct` | no gateway | Ollama | the bank's MCP server | nobody: no key, no identity, no policy |

How a turn goes, behind the gateway:

1. bank-web calls Ace through the A2A proxy with the user's AM access token. Ace reads it from the request headers: its
   claims (`name`, `role`, `customer_id`, `accounts`) name the user in the system prompt, nothing more (never a decision).
2. Ace exchanges that token at AM (RFC 8693, Ace's own token as the actor) for one that says `sub` = the user and
   `act.sub` = Ace. It is kept until it expires, per user token. If AM refuses, does not answer, or issues a token that
   does not say both, Ace acts for nobody: no model call, no tool call, a fixed sentence ("I cannot act for you right
   now") and an `exchange` row that says why. With the user's own token the bank's policies could not tell Ace from the
   user and the agent's limits would not apply. `DELEGATION=off` skips the exchange and sends the user's token as it is.
   Ace keeps its own token until it expires. When AM refuses an exchange (for example after its domain is set up again),
   Ace asks for a new token of its own and tries once more, never twice.
3. Ace lists the tools with that token (the MCP proxy shows only what the role may use), then asks the model, at most 4
   times. Each tool call goes to the MCP proxy, which decides it. A refusal is shown to the model as a tool result.
4. Ace answers with one message and no task: a text part, and a data part with what happened.

Ace answers each message on its own: it does not remember the earlier ones. Its system prompt is a routing table written
for qwen3:1.7b, with the user's name, customer id and accounts in one parenthesis (`prompt.py` says why they are written
like that, why there is no directory of customers and why a question that names an account is asked without the user's
accounts).

## Endpoints

`POST /` A2A 1.0 JSON-RPC (`SendMessage`, header `A2A-Version: 1.0`), `GET /.well-known/agent-card.json` and the same
card at `GET /.well-known/agent.json` (the legacy path: through the A2A proxy a 404 there is a 500), `GET /health`. The
container logs one line per step (`llm`, `exchange`, `tool`), never arguments or tokens.

Ace asks no one who they are: the published port of `bank-agent-direct` runs a chat, and calls the bank's tools, for
whoever calls it. So a web page must not be able to make your browser call it. A `POST` needs `Content-Type:
application/json` (`415` otherwise: a page can send plain text or a form without asking the browser's leave, and
JSON only after a preflight that Ace never allows), and every request but `/health` needs a `Host` from
`ALLOWED_HOSTS` (`421` otherwise: the DNS rebinding trick sends its own name). The Compose file adds the service's own
name, which is how the gateway and bank-web reach it; give your own host name in `ALLOWED_HOSTS` when the gateway
reaches Ace by another.

### Data part

```json
{"trace": [{"step": "exchange | llm | tool", "name": "...", "outcome": "ok | denied | blocked | rate_limited | error",
            "ms": 12, "detail": "...", "arguments": {}, "status": 200, "transaction_id": "...", "request_id": "..."}],
 "tools": ["list_accounts", "get_balance"],
 "delegated_claims": {"sub": "...", "act": {"sub": "ace-agent"}, "role": "customer"}}
```

- `trace` rows in order: the token exchange (`name` `token-exchange`; when it fails it is the only row and `tools` is
  empty), the tool listing (`tools/list`), each model call (`name` is the model) and each tool call. `transaction_id`
  and `request_id` are the gateway's, for Logs and Decisions.
  Ace sends the transaction id of the A2A call (the `X-Gravitee-Transaction-Id` header the proxy forwards) on every call
  it makes to the gateway, which keeps it: all the rows of a turn have the same `transaction_id`, so one filter in Logs
  shows the whole turn, while `request_id` stays one per call, which is what a decision is filed under. Called without
  the gateway, the rows have no ids.
  A refused model call has `blocked_by: llm-proxy`. A session that could not start is one row named `connect`.
- `tools` are the names the user may use: what the MCP proxy lists for them.
- `delegated_claims` is the decoded delegated token (unverified, for display), present when the exchange worked.
- Numbers come back as floats over A2A (`"ms": 12.0`).

## Environment

| Variable | Meaning | `bank-agent` | `bank-agent-direct` |
|---|---|---|---|
| `LLM_URL` | OpenAI-compatible base URL | `.../acme-bank/llm` on the gateway | `${OLLAMA_URL}/v1` |
| `LLM_MODEL` | model alias, or model name | `acme-chat` | `qwen3:1.7b` |
| `LLM_API_KEY` | Ace's key at the LLM proxy, sent as `Authorization: Bearer` | the `Ace agent` plan key | empty |
| `LLM_REASONING_EFFORT` | thinking of the model, `none` when it is not set; set and empty, no effort is sent | default | default |
| `MCP_URL` | the bank's tools, no trailing slash on the gateway | `.../acme-bank/mcp` on the gateway | `http://bank-mcp:8000/` |
| `DELEGATION` | `on` or `off` (default `on`) | `on` | `off` |
| `AM_TOKEN_URL` | AM token endpoint of the domain, needed with `DELEGATION=on` | `.../acme-bank/oauth/token` | |
| `AGENT_CLIENT_ID`, `AGENT_CLIENT_SECRET` | Ace's application at AM, needed with `DELEGATION=on` | `ace-agent` | |
| `PUBLIC_URL` | where clients call Ace, in the agent card (default `http://localhost:HTTP_PORT`) | the A2A proxy's URL | |
| `HTTP_PORT` | port to listen on (default `8000`) | | |
| `ALLOWED_HOSTS` | names Ace is reached by, comma separated, without port (default `localhost,127.0.0.1,[::1]`) | `bank-agent` and the loopback names | `bank-agent-direct` and the loopback names |

`LLM_URL`, `LLM_MODEL` and `MCP_URL` are required: a missing one stops the container and says which.

The token a request carries goes to the MCP URL as it is only when `DELEGATION=off`. A request with no token calls the
tools with none: the gateway answers 401, the direct Ace works.

## Run

Compose runs the image twice with the playground (`bank-agent` and `bank-agent-direct`). On its own, it needs the three
required settings; `DELEGATION=off` skips the token exchange at AM:

```bash
docker build -q -t bank-agent . && docker run --rm -p 127.0.0.1:8000:8000 -e DELEGATION=off \
  -e LLM_URL=<OpenAI-compatible URL> -e LLM_MODEL=<model> -e MCP_URL=<MCP server URL> bank-agent
```

The agent card is then at `http://localhost:8000/.well-known/agent-card.json`.

## Tests

`make test-apps` from the repository root runs the tests of every app in its image. For this app alone, from this folder:

```bash
docker build -q -t bank-agent-test . && docker run --rm --entrypoint python bank-agent-test -m unittest discover -s tests -t .
```

Without Docker, in a Python 3.14 virtual environment with the pins of `requirements.txt`:
`python -m unittest discover -s tests -t .` from this folder.

The fakes in `tests/fakes.py` stand in for the model (a stub OpenAI server), the bank (an in-memory MCP server with the
real tool names), the gateway (it checks the token, refuses a tool and stamps transaction ids) and AM, all in memory.
