# ACME Bank

ACME Bank built Ace, an AI assistant for its customers and its tellers. In this playground you put Ace in production with Gamma, Gravitee's console for AI agents, MCP servers and LLM traffic: its lessons start with the protections switched off, you see the problem, find the protection in Gamma, switch it on and try again. It takes about 35 minutes.

All of ACME Bank's data is invented: its people, accounts, branches and addresses. The email addresses end in `.test`, which no real address uses.

## What you need

| Need | Details |
|---|---|
| An Enterprise license | It must include Gamma's Agent Management and Authorization modules, and the MCP proxy. Add it from the **CE** chip of the Lab UI's Containers page. To get one, see [What needs a license](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/installation.md#what-needs-a-license). |
| Pre-release (alpha) builds of 4.13 of API Management and Access Management | Gravitee 4.13 is in alpha: choose the 4.13 tags on the Images page. API Management needs 4.13.0-alpha.3 or later, and Access Management 4.13 or later, because the core's default versions are older. The playground's page says so under **Before you start**, and Start names every image that is too old in one sentence. |
| Ollama on your machine, with `qwen3:1.7b` and `qwen3:0.6b` | See [Start it](#start-it). ACME Bank on Windows is untested; the Ollama setup for it is not verified. |
| Internet access | The gateway downloads its AI models (129 MB) from huggingface.co the first time it deploys the LLM proxy. Without access the seed, a one-time job that creates the playground's sample APIs and users, ends with a timeout. |
| 10 GB of memory for Docker | |
| A recent browser | ACME Bank app: Chrome or Edge 123, Firefox 120 or Safari 17.5, or later, because its colors use `light-dark()`. The Lab UI that shows it needs Chrome or Edge 117, Firefox 121 or Safari 16.4, or later. |

The Lab UI checks the license features before you start. They are in the `requires` block of [`compose.yml`](compose.yml).

## Start it

1. Install Ollama from [ollama.com/download](https://ollama.com/download), then pull the two models:

   ```bash
   ollama pull qwen3:1.7b
   ```

   ```bash
   ollama pull qwen3:0.6b
   ```

   The containers must be able to reach Ollama. On Linux and WSL 2 it listens on `127.0.0.1` only by default, which they cannot reach, so start Ollama with `OLLAMA_HOST` set to the address of Docker's bridge, which the containers reach as `host.docker.internal`. Find the address:

   ```bash
   docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'
   ```

   Ollama then answers on that address only, so the Lab UI's check at `localhost` warns that it is not reachable. If that does not work, use `OLLAMA_HOST=0.0.0.0`, which makes Ollama listen on every network interface, with no sign-in: use a firewall. [Troubleshooting](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/troubleshooting.md#ollama-is-not-reachable-from-the-containers) has the steps. If Ollama runs somewhere else, set `OLLAMA_URL`.

2. Run `make ui`, open **Playgrounds** > **ACME Bank**, and fix the warnings under **Before you start**.
3. Click **Start**. The first start takes about 10 minutes after the images are pulled: it builds the apps, starts the platform and runs the seed. When the start ends, the page shows the guide next to the ACME Bank app and Gamma.

The apps are built here from `apps/` at each start. Set `ACME_BANK_PULL_POLICY` to `always` to pull the images that CI builds instead: [Built here, or pulled](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/configuration.md#built-here-or-pulled) has the details.

## Accounts and URLs

| What | Address |
|---|---|
| ACME Bank app | http://localhost:8110 |
| Gamma console | http://localhost:8086 |
| APIM Console | http://localhost:8084 |
| Access Management console | http://localhost:8081 |
| The bank's MCP server, unprotected: calling it skips the gateway | http://localhost:8111 |
| Ace, behind the gateway's A2A proxy | http://localhost:8112 |
| The bank's open REST API | http://localhost:8113 |
| Ace with no gateway, identity or policy | http://localhost:8114 |

| Account | Sign-in |
|---|---|
| Alice and Bob, customers | `alice@acme-bank.test`, `bob@acme-bank.test` |
| Tina, teller | `tina@acme-bank.test` |
| Password of Alice, Bob and Tina | `HelloWorld@123`, a public demo value that `ACME_BANK_DEMO_PASSWORD` sets |
| Gamma and APIM consoles | `admin` / `admin` |
| Access Management console | `admin` / `adminadmin` |

The playground's **Details** tab lists these accounts with copy buttons. A password or key there is the value of its setting now, in the order of [Settings](#settings). The admin passwords in the table above are the defaults of `ACME_BANK_APIM_PASSWORD` and `ACME_BANK_AM_PASSWORD`. The other demo values are in [Logins](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/configuration.md#logins).

## Settings

Set them from the key button of the playground in the Lab UI. Compose reads a setting from the shell first, then the root `.env`, then the playground's own `.env`, then the default. The **Details** tab follows the same order.

| Setting | Default | Meaning |
|---|---|---|
| `ACME_BANK_PROTECTIONS` | `off` | `off`: the lessons switch the protections on. `on`: everything is protected from the start, for presenting. See [below](#switch-the-protections-on-from-the-start) |
| `ACME_BANK_TRAFFIC` | `on` | `off` starts the traffic generator paused, until the app's Presenter view resumes it |
| `ACME_BANK_TRAFFIC_RATE` | `1` | How fast it sends, from 0.1 to 10: 1 is one scenario every 2 minutes |
| `ACME_BANK_PULL_POLICY` | `build` | `build` builds the apps here at each start, `always` pulls the published images and builds them here if a pull is refused |
| `ACME_BANK_GATEWAY_READY_TIMEOUT` | `300` | Seconds the seed waits for the gateway to serve each API |
| `ACME_BANK_APIM_PASSWORD` | `admin` | Password of user `admin` in API Management, which the seed, the web app and the traffic generator sign in with. Set it if you changed that password in the console |
| `ACME_BANK_AM_PASSWORD` | `adminadmin` | Password of user `admin` in Access Management, which the seed signs in with. Set it if you changed that password in the console |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Where Ollama listens, as the containers reach it |
| `GEMINI_API_KEY` | empty | An optional Google AI Studio key. With one, the catalog gets a Gemini provider (Gamma tests the key against Google as it creates it); empty seeds no Gemini provider |

The playground's own settings start with `ACME_BANK_`. `OLLAMA_URL` and `GEMINI_API_KEY` name a host service and keep its common name.

The demo secrets are settings too: `ACME_BANK_DEMO_PASSWORD`, `ACME_BANK_WEB_CLIENT_SECRET`, `ACME_BANK_TRAFFIC_CLIENT_SECRET`, `ACME_BANK_ACE_CLIENT_SECRET`, `ACME_BANK_MCP_RESOURCE_SECRET`, `ACME_BANK_ACE_LLM_API_KEY`, `ACME_BANK_DEV_LLM_API_KEY`, `ACME_BANK_TRAFFIC_LLM_API_KEY` and `ACME_BANK_ADMIN_TOKEN`. Set them before the first start. The seed writes the passwords, secrets and API keys into Access Management and the APIs when it creates them, and keeps what it finds on later runs, so on a lab that is already set up a new value needs a reset. `ACME_BANK_ADMIN_TOKEN` is the exception: the apps read it directly, so *Save & apply* is enough.

## What you learn

An agent in production answers three questions. Each lesson belongs to one:

| Question | Lessons |
|---|---|
| What may it do? | 2 Protect the model, 3 Protect the tools, 4 Decide who may do what, 5 Cap what an agent may do |
| What does it cost? | 6 Cap what teams spend |
| What did it do? | 1 See everything, 7 Prove it |

The lessons are in [`guide.md`](guide.md). The Lab UI shows it next to the running app and Gamma.

## Start the lessons over

[Start again](guide.md#start-again) in the guide lists what to click. *Re-seed* puts every protection back in the state `ACME_BANK_PROTECTIONS` names, and fills the budget of the Hackathon sandbox team, which lesson 6 spends.

## Presenter view

The app's **Presenter** view checks that the bank is ready, warms up the models, pauses and resumes the traffic generator, and starts the bank over. The guide ends with a 15-minute path for presenters. The view's routes are `/api/presenter/*`: see the [web app's README](apps/bank-web/README.md).

## Switch the protections on from the start

Two things read `ACME_BANK_PROTECTIONS`, so a change takes two steps:

1. Change it in the settings and click *Save & apply*. This recreates the traffic generator, which reads the mode when its container is made: strict when the protections are on, accepting either outcome when they are off.
2. Click *Re-seed*. This runs the seed again: it puts every protection back in the state the setting says, whatever you switched in the consoles since, and gives the Hackathon sandbox its budget back, which needs the lab's Redis.

Re-seed alone leaves the traffic generator in the mode it started with. So after a change: *Save & apply*, then *Re-seed*.

## Delete the logs

Gamma's Logs keep the payloads of the calls through the LLM, MCP and A2A proxies and the AI workspace, and not their headers, which hold the bearer token of a person or the key of a team. They stay in Elasticsearch (port 9200 of this machine) until the lab is reset. The OpenTelemetry records are in the data streams of [Gamma Tracing](../../addons/gamma-tracing/README.md#what-it-keeps), which that README shows how to clear.

Both commands below are optional maintenance. The Logs are plain daily indices, `gravitee-v4-log-*`. They are not data streams, and Elasticsearch refuses to delete indices by a wildcard, so the equivalent is a query. To keep the logs and remove the headers from any record that holds them:

```
curl -X POST 'http://localhost:9200/gravitee-v4-log-*/_update_by_query?conflicts=proceed' -H 'Content-Type: application/json' -d '{
  "query": {"match_all": {}},
  "script": {"lang": "painless",
             "source": "for (def part : [\"entrypoint-request\", \"entrypoint-response\", \"endpoint-request\", \"endpoint-response\"]) { def o = ctx._source.get(part); if (o instanceof Map) { o.remove(\"headers\"); } }"}}'
```

To delete the logs altogether (the metrics indices, `gravitee-v4-metrics-*`, stay):

```
curl -X POST 'http://localhost:9200/gravitee-v4-log-*/_delete_by_query?conflicts=proceed' -H 'Content-Type: application/json' -d '{"query": {"match_all": {}}}'
```

## What stays after a removal

[The guide](guide.md#what-stays-after-a-removal) says what stays in Gravitee, in Elasticsearch and in Redis after **Delete what it created**. The gateway's models volume, `data-acme-bank-gateway-models`, stays too. Two files stay on your machine: the record of what the seed created, which is empty after a removal, and your settings. **Reset**, in the Containers page's menu, deletes every container and volume, and empties the record. It leaves your settings.

## More

- [`guide.md`](guide.md): the lessons, "If something does not work" and "For presenters".
- The apps: [bank-web](apps/bank-web/README.md), [bank-agent](apps/bank-agent/README.md), [bank-mcp](apps/bank-mcp/README.md), [bank-api](apps/bank-api/README.md) and [bank-traffic](apps/bank-traffic/README.md).
- [Writing a playground](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/playgrounds.md).
