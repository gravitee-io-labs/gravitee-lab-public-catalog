# Gravitee public

Playgrounds, setups and add-ons of the Lab

This is a catalog for [Gravitee Lab](https://github.com/gravitee-io-labs/gravitee-lab): add-ons, setups and playgrounds that the Lab shows in its pages and starts with Docker Compose.

## Add it to the Lab

A new install of the Lab already lists it, as **Gravitee public**. If you removed it, or it is not there:

1. Open **Library > Catalogs**.
2. Click **Add catalog**.
3. Enter `gravitee-io-labs/gravitee-lab-public-catalog`.
4. Read the preview, then confirm.

From a terminal:

```bash
python3 lab-ui/catalog.py add gravitee-io-labs/gravitee-lab-public-catalog
```

## What it holds

| Folder | Holds |
|---|---|
| `addons/` | One folder for each add-on: a `compose.yml` and a README |
| `setups/` | One file for each setup: `<name>.yml` |
| `playgrounds/` | One folder for each playground: a `compose.yml`, a README, a guide and a seed |

The add-ons are Kafka, Solace, Jaeger, Kibana, OpenFGA, Kubernetes and its dashboard, the Gravitee Kubernetes Operator, API
federation agents, a hybrid gateway, Gamma tracing, a mail catcher and inspectors for MCP and agents. The setups start some of
them together. The playgrounds are ACME Bank, ACME Hotels, ACME Hotels API, ACME Logistics and Apexora Bio: each has its apps,
its sample data and a guide. Their format is [the Lab's](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/units.md).

## Ports

Every port is published on `127.0.0.1`, so only this machine reaches it. The ports of the Lab's core are in the Lab's
[configuration](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/configuration.md#ports). The ports of the items of this catalog:

| Port | Service | What it is | Login |
|---|---|---|---|
| 2525 | `smtp4dev` | SMTP of the Mail server add-on | – |
| 3000 | `openfga` | OpenFGA Playground | – |
| 4317 | `jaeger` | OTLP gRPC of the Jaeger add-on | – |
| 4318 | `jaeger` | OTLP HTTP of the Jaeger add-on | – |
| 5080 | `smtp4dev` | Web UI of the Mail server add-on | – |
| 5540 | `redisinsight` | RedisInsight, already connected to Redis | – |
| 5601 | `kibana` | Kibana | – |
| 6274 | `mcp-inspector` | MCPJam Inspector | A session token in its console link |
| 8080 | `kafka-console` | Kafka Console | – |
| 8088 | `kafka-ui` | Kafka UI | – |
| 8090 | `apim-hybrid-gateway` | Hybrid gateway, HTTP entrypoint | – |
| 8110 | `bank-web` | ACME Bank web app | The accounts of the playground |
| 8111 | `bank-mcp` | ACME Bank MCP server, unprotected: calling it skips the gateway | – |
| 8112 | `bank-agent` | Ace, behind the gateway's A2A proxy | – |
| 8113 | `bank-api` | ACME Bank open REST API | – |
| 8114 | `bank-agent-direct` | Ace with no gateway, identity or policy | – |
| 8120 | `acme-hotels-web` | ACME Hotels website | The accounts of the playground |
| 8121 | `acme-hotels-backend` | ACME Hotels REST API, unprotected: calling it skips the gateway | – |
| 8122 | `acme-hotels-api` | ACME Hotels API, unprotected: calling it skips the gateway | – |
| 8180 | `openfga` | OpenFGA HTTP API | – |
| 8181 | `openfga` | OpenFGA gRPC API | – |
| 9002 | `agent-inspector` | AI Agent Inspector | – |
| 9091 | `kafka` | Kafka broker, PLAINTEXT | – |
| 9094 | `kafka` | Kafka broker, SSL | – |
| 9095 | `kafka` | Kafka broker, SASL_PLAINTEXT | `gravitee_user` / `gravitee_password` |
| 9096 | `kafka` | Kafka broker, SASL_SSL | `gravitee_user` / `gravitee_password` |
| 11434 | Ollama | Ollama on your machine, for ACME Bank and ACME Hotels. It is not part of the lab | – |
| 16686 | `jaeger` | Jaeger UI | – |

## Logins and secrets

The logins are public demo values, for your machine only. Each has a setting that changes it.

| Where | User | Password | Setting |
|---|---|---|---|
| Kafka, SASL listeners (9095, 9096) | `gravitee_user` | `gravitee_password` | `KAFKA_CLIENT_PASSWORD` |
| Kafka Console, its calls to the Management API (inside Docker) | `admin` | `admin` | `KAFKA_CONSOLE_APIM_PASSWORD` |
| MCPJam Inspector | | A session token, in its console link: see [Other demo secrets](#other-demo-secrets) | |
| ACME Bank: Alice and Bob (customers), Tina (teller) | `alice@acme-bank.test`, `bob@acme-bank.test`, `tina@acme-bank.test` | `HelloWorld@123` | `ACME_BANK_DEMO_PASSWORD` |

| Where | Value | Setting |
|---|---|---|
| ACME Hotels: John Doe (guest) | `john.doe@gravitee.io` | `HelloWorld@123` | `ACME_HOTELS_DEMO_PASSWORD` |
| Keystore of the Kafka gateway (`addons/kafka/certs/kafka-gateway.p12`) | `gravitee` | `KAFKA_GATEWAY_KEYSTORE_PASSWORD` |
| Kafka broker, controller user | `controller_user` / `controller_password` | `KAFKA_CONTROLLER_PASSWORD` |
| Kafka broker, user between brokers | `inter_broker_user` / `inter_broker_password` | `KAFKA_INTER_BROKER_PASSWORD` |
| OpenFGA database (inside Docker only) | `openfga` / `openfga` | `OPENFGA_POSTGRES_PASSWORD` |
| Kafka Console, signing secret | `gravitee-lab-kafka-console-demo-secret` | `KAFKA_CONSOLE_SECRET` |
| MCPJam Inspector, session token | `gravitee-lab-local-inspector` | `MCP_INSPECTOR_SESSION_TOKEN` |
| ACME Bank, its sign-in to API Management and to Access Management (the seed, the web app, the traffic generator) | `admin` / `admin` and `admin` / `adminadmin` | `ACME_BANK_APIM_PASSWORD`, `ACME_BANK_AM_PASSWORD` |
| ACME Bank, Access Management application secrets | `acme-bank-web`, `acme-bank-traffic`, `ace-agent`, `acme-bank-mcp` | `ACME_BANK_WEB_CLIENT_SECRET`, `ACME_BANK_TRAFFIC_CLIENT_SECRET`, `ACME_BANK_ACE_CLIENT_SECRET`, `ACME_BANK_MCP_RESOURCE_SECRET` |
| ACME Bank, LLM proxy keys | `acme-ace-llm-key`, `acme-dev-llm-key`, `acme-traffic-llm-key` | `ACME_BANK_ACE_LLM_API_KEY`, `ACME_BANK_DEV_LLM_API_KEY`, `ACME_BANK_TRAFFIC_LLM_API_KEY` |
| ACME Bank, token that resets the bank's data | `acme-bank-admin` | `ACME_BANK_ADMIN_TOKEN` |
| ACME Hotels, its sign-in to API Management and to Access Management (the seed) | `admin` / `admin` and `admin` / `adminadmin` | `ACME_HOTELS_APIM_PASSWORD`, `ACME_HOTELS_AM_PASSWORD` |
| ACME Hotels, Access Management application secrets | `hotel-ai-agent`, `hotel-mcp` | `ACME_HOTELS_AGENT_CLIENT_SECRET`, `ACME_HOTELS_MCP_RESOURCE_SECRET` |
| ACME Hotels API, its sign-in to API Management (the seed) | `admin` / `admin` | `ACME_HOTELS_API_APIM_PASSWORD` |

These have no login: Kibana, RedisInsight, Jaeger, Kafka UI, the mail server, OpenFGA and the AI Agent Inspector.
A database or a broker keeps the credentials it was created with in its volume: set them before the first start.

## Images and pull policies

A setting per item switches it to the images that CI builds: `ACME_BANK_PULL_POLICY` (ACME Bank apps and seed), `ACME_HOTELS_PULL_POLICY`,
`MCP_INSPECTOR_PULL_POLICY` (default `build`) and `AGENT_INSPECTOR_PULL_POLICY` (default `never`). The catalog's CI publishes the images to the
registry that `images` names in `catalog.yml`, as `latest` and `sha-<commit>`, and `catalog.py check` says the name each service expects. The apps
of ACME Hotels and the AI Agent Inspector are built from another project's source.

## Develop

Clone this repository next to a clone of Gravitee Lab (`../gravitee-lab`, or set `LAB=/path/to/gravitee-lab`), then:

| Command | Does |
|---|---|
| `make dev` | Opens this catalog in the Lab |
| `make check` | Runs the rules CI runs, on the files and on the commits since `origin/main` |
| `make ci` | Also builds, tests and starts the apps on this machine (needs Docker) |
| `make explain CODE=ST05` | Says more about a rule |

## Contribute

Open a pull request. [CONTRIBUTING.md](CONTRIBUTING.md) says how, [REVIEWING.md](REVIEWING.md) is what a maintainer reads, and [SECURITY.md](SECURITY.md) says where to report a problem.
