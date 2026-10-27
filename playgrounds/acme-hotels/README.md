# ACME Hotels

ACME Hotels built an AI agent that answers its guests on the hotel website. In this playground you put that agent behind the Gravitee gateway: the gateway caches its questions, limits its tokens, blocks risky prompts, and, with Access Management and OpenFGA, decides which bookings a guest may see. It takes about 30 minutes.

It is the playground of the [Gravitee AI Agent Workshop](https://github.com/gravitee-io-labs/Gravitee-AI-Agent-Workshop): the hotel website, the hotels' REST API and the agent are built here from that repository, at a fixed commit. All of ACME Hotels' data is invented: its hotels, bookings and guest.

## What you need

| Need | Details |
|---|---|
| An Enterprise license | It must include the AI features of API Management (the LLM, A2A and MCP tool server proxies, semantic caching, PII filtering and the AI models), the OpenFGA authorization engine and the AuthZEN endpoint of Access Management, and the TCP reporter of the AI Agent Inspector. Add it from the **CE** chip of the Lab UI's Containers page. To get one, see [What needs a license](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/installation.md#what-needs-a-license). |
| API Management and Access Management 4.12 or later | The core's default versions fit. The playground's page checks the versions before you start. |
| Ollama on your machine, with `qwen3:0.6b` | See [Start it](#start-it). ACME Hotels on Windows is untested; the Ollama setup for it is not verified. |
| Internet access | The first start builds the apps from GitHub, with their packages from PyPI, and downloads the plugin `gravitee-policy-interrupt` from download.gravitee.io. The gateway downloads its AI models (129 MB) from huggingface.co the first time it deploys the LLM proxy. Without that access the seed, a one-time job that creates the playground's sample APIs and guest, ends with a timeout. |
| 10 GB of memory for Docker | |

The Lab UI checks the license features before you start: those in the `requires` block of [`compose.yml`](compose.yml), and those of the plugins that the APIs use.

## Start it

1. Install Ollama from [ollama.com/download](https://ollama.com/download), then pull the model:

   ```bash
   ollama pull qwen3:0.6b
   ```

   The containers must be able to reach Ollama. On Linux and WSL 2 it listens on `127.0.0.1` only by default, which they cannot reach: [Troubleshooting](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/troubleshooting.md#ollama-is-not-reachable-from-the-containers) has the steps. If Ollama runs somewhere else, set `OLLAMA_URL`.

2. Run `make ui`, open **Playgrounds** > **ACME Hotels**, and fix the warnings under **Before you start**.
3. Click **Start**. The first start takes about 10 minutes after the images are pulled: it builds the apps, installs the `gravitee-policy-interrupt` plugin, starts the platform and the add-ons the playground brings, and runs the seed. When the start ends, the page shows the guide next to the APIM Console and Gamma.

The apps are built here from the workshop repository at each start. Set `ACME_HOTELS_PULL_POLICY` to `always` to pull the images that CI builds instead: [Built here, or pulled](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/configuration.md#built-here-or-pulled) has the details.

## Ports and URLs

| Port | What it is | Login |
|---|---|---|
| 8120 | The ACME Hotels website, http://localhost:8120 | The guest below |
| 8121 | The hotels' REST API, unprotected: calling it skips the gateway. Documentation: http://localhost:8121/docs | None |

Every port binds `127.0.0.1`. The agent's card is behind the gateway's A2A proxy, at http://localhost:8082/hotel-agent/.well-known/agent-card.json. The lessons also use the consoles of the platform:

| Port | Console | Login |
|---|---|---|
| 8084 | APIM Console, http://localhost:8084 | `admin` / `admin` |
| 8086 | Gamma, http://localhost:8086 | `admin` / `admin` |
| 8081 | Access Management console, http://localhost:8081 | `admin` / `adminadmin` |

The add-ons the playground brings have their own ports and logins: [AI Agent Inspector](../../addons/ai-agent-inspector/README.md) (9002), [OpenFGA](../../addons/openfga/README.md) (3000), [RedisInsight](../../addons/redisinsight/README.md) (5540) and [MCPJam Inspector](../../addons/mcpjam-inspector/README.md) (6274).

## Logins and secrets

Everything here is a public demo value, for your machine only. The playground's **Details** tab lists the accounts with copy buttons; a password there is the value of its setting now.

| Account | Sign-in | Password | Setting |
|---|---|---|---|
| John Doe, guest of the website | `john.doe@gravitee.io` | `HelloWorld@123` | `ACME_HOTELS_DEMO_PASSWORD` |
| Gamma and APIM consoles | `admin` | `admin` | `ACME_HOTELS_APIM_PASSWORD` |
| Access Management console | `admin` | `adminadmin` | `ACME_HOTELS_AM_PASSWORD` |

The two admin settings are the passwords the seed signs in with: set them if you changed those passwords in a console.

| Secret | Value | Setting |
|---|---|---|
| Access Management application secrets | `hotel-ai-agent`, `hotel-mcp` | `ACME_HOTELS_AGENT_CLIENT_SECRET`, `ACME_HOTELS_MCP_RESOURCE_SECRET` |

Set them before the first start. The seed writes the password and the secrets into Access Management when it creates them, and keeps what it finds on later runs, so on a lab that is already set up a new value needs a reset. Write `ACME_HOTELS_MCP_RESOURCE_SECRET` in letters, digits and dashes: the gateway's script for the bookings, which the seed also writes into the API, uses it in a string.

## Settings

Set them from the key button of the playground in the Lab UI. Compose reads a setting from the shell first, then the root `.env`, then the playground's own `.env`, then the default. The **Details** tab follows the same order.

| Setting | Default | Meaning |
|---|---|---|
| `ACME_HOTELS_PULL_POLICY` | `build` | `build` builds the apps and the seed here at each start, `always` pulls the published images and builds them here if a pull is refused |
| `ACME_HOTELS_GATEWAY_READY_TIMEOUT` | `300` | Seconds the seed waits for the gateway to serve each API |
| `ACME_HOTELS_APIM_PASSWORD` | `admin` | Password of user `admin` in API Management, which the seed signs in with. Set it if you changed that password in the console |
| `ACME_HOTELS_AM_PASSWORD` | `adminadmin` | Password of user `admin` in Access Management, which the seed signs in with. Set it if you changed that password in the console |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Where Ollama listens, as the containers reach it |
| `GEMINI_API_KEY` | empty | An optional Google AI Studio key for the Gemini model of the LLM proxy. Empty stores a placeholder |

The playground's own settings start with `ACME_HOTELS_`. `OLLAMA_URL` and `GEMINI_API_KEY` name a host service and keep its common name.

The demo secrets and passwords are settings too: they are in [Logins and secrets](#logins-and-secrets).

## What you learn

| Lesson | What the gateway does |
|---|---|
| 1 Cache similar questions | Answers a question close in meaning to an earlier one from its cache, without calling the model |
| 2 Limit tokens | Stops a caller that spent its tokens before the model is reached |
| 3 Block risky prompts | Reads each prompt with a small model and rejects the malicious ones |
| 4 Sign in and authorize | Accepts only the token that the agent got by exchange, and filters the bookings with OpenFGA |
| 5 Look at the agent's tools | Turns the hotels' REST API into MCP tools that any MCP client finds |

The lessons are in [`guide.md`](guide.md). The Lab UI shows it next to the running consoles.

## Start the lessons over

The lessons can be done again as they are: the cache forgets an entry after a minute and the token limit starts over every 15 seconds. *Re-seed* runs the seed again: it changes nothing that is already as the files say.

## What stays after a removal

**Stop** with **Delete what it created** removes what the seed created in Gravitee: the four APIs and the application of API Management, and the domain `acme-hotels` of Access Management, with its guest, its applications and its MCP server, and the OpenFGA store. A few things stay:

- the gateway's models volume, `data-acme-hotels-gateway-models`, so that the next start does not download the AI models again
- the history of the calls in Elasticsearch, and the cache and the counters in Redis
- the plugin `gravitee-policy-interrupt`, in `plugins/apim` on your machine
- the volumes of the add-ons the playground brings, such as `data-openfga` and `data-mcp-inspector`
- the images built here
- two files on your machine: the record of what the seed created, which is empty after a removal, and your settings

**Reset**, in the Containers page's menu, deletes every container and volume, and empties the record. It leaves the plugin, the images and your settings.

## More

- [`guide.md`](guide.md): the lessons and "If something does not work".
- [The Gravitee AI Agent Workshop](https://github.com/gravitee-io-labs/Gravitee-AI-Agent-Workshop), where the apps come from.
- [Writing a playground](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/playgrounds.md).
