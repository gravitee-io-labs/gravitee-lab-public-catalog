# Hybrid gateway

An APIM gateway that gets its APIs and configuration from your Gravitee Cloud control plane, and runs on your machine in the lab's Docker network, so the APIs you manage in Cloud can reach the lab's containers as backends. It is a second gateway, next to the lab's own: it uses neither the lab's Management API nor its Redis, which it has its own of, so starting it starts nothing of the core. The whole path, from the Cloud account to the first call: [Use Gravitee Cloud with the Lab](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/cloud.md).

## Needs

- A hybrid gateway defined in Gravitee Cloud, and its token in `HYBRID_GATEWAY_CLOUD_TOKEN`. The add-on shows **Settings** instead of **Start** until it has the token, and **Needs a hybrid gateway** with a link to the Gravitee Cloud page once you connected a Gravitee Cloud account. The token comes from one of two places:
  - The Lab's Gravitee Cloud page, which writes it in this add-on's settings when it creates or starts the gateway.
  - The Cloud console, Dashboard > Deploy Gateway > Hybrid Gateway, which shows the token once.
- A license key with the feature `apim-bridge-gateway`, in `HYBRID_GATEWAY_LICENSE`. The wizard of the Cloud console issues a License Key of its own. The gateway never reads the core's `GRAVITEE_LICENSE`: give the key here, even when it is the same one. The add-on shows **Settings** instead of **Start** until it has one.
- Outbound HTTPS from your machine to Gravitee Cloud.

## Ports

| Port | What it is | Login |
|---|---|---|
| 8090 | The gateway's HTTP entrypoint, http://localhost:8090 | None: an API of your Cloud environment decides |

It listens on `127.0.0.1` only. Its internal API (18082) and its Redis (6379) are on the Docker network only.

## Logins and secrets

| What | Value | Setting |
|---|---|---|
| Token of the hybrid gateway | Written by the Lab's Gravitee Cloud page, or pasted from the Cloud console | `HYBRID_GATEWAY_CLOUD_TOKEN` |
| License key | Yours, with the feature `apim-bridge-gateway` | `HYBRID_GATEWAY_LICENSE` |
| Password of the gateway's internal API, user `admin` | `adminadmin`, a public demo value, shared with the core | `INTERNAL_API_PASSWORD` |
| Password of the add-on's Redis | `redispassword`, a public demo value, shared with the core | `REDIS_PASSWORD` |

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `HYBRID_GATEWAY_CLOUD_TOKEN` | none | The token of the hybrid gateway that runs here. The Gravitee Cloud page writes it when it creates the first gateway or starts another |
| `HYBRID_GATEWAY_LICENSE` | none | A license key with the feature `apim-bridge-gateway` |
| `HYBRID_GATEWAY_VERSION`, `HYBRID_GATEWAY_REGISTRY` | `4.12.23-debian`, `graviteeio` | Version and Docker registry of the gateway image, chosen on the Images page. The Debian image is what the AI policies need, like the core's gateway. Keep its minor version equal to your control plane's |
| `HYBRID_REDIS_VERSION` | the core's Redis version | Version of the Redis image of the add-on, chosen on the Images page |

They stay on your machine, in a file that git ignores.

## Use it

- **Host.** The gateway matches a request only when its `Host` equals a domain registered for the environment in Cloud, port included. The Lab registers two when it creates a gateway: `localhost:8090`, for `curl http://localhost:8090/<path>` and your browser, and `apim-hybrid-gateway:8082`, for a container of the lab. In the Cloud wizard, enter `localhost:8090` as the HTTP domain. A request with another `Host`, `127.0.0.1:8090` for one, answers 404 `No context-path matches the request URI`.
- **One gateway at a time.** The add-on runs the gateway whose token `HYBRID_GATEWAY_CLOUD_TOKEN` holds. Starting another gateway of the account from the Gravitee Cloud page, or deploying a playground to an environment this one does not serve, writes the other's token and recreates the container, after saying so. Each gateway serves one environment.
- **Backends.** The gateway runs in the lab's internal network, so an API in Cloud reaches a container as `http://<service>:<container port>`, for example `http://bank-api:8000`, the open API of ACME Bank. `localhost` in a backend URL means the gateway container itself. `host.docker.internal` is this machine.
- **The link to Cloud.** The gateway pulls its APIs from Cloud every 10 seconds, and sends its analytics to Cloud, not to the lab's Elasticsearch. A gateway that restarts without a link to Cloud loads no APIs. The Cloud console shows the gateway as connected once a node has started.
- **Rate limits.** The counters are in the add-on's own Redis, `hybrid-redis`. The two gateways share no counter.
- **Gravitee Cloud.** `x-gravitee.gateway` in `compose.yml` says that this add-on runs the gateway of a Gravitee Cloud on this machine: which service, and which setting takes the token. The Lab finds the add-on by it, and derives the domains of the gateway from the port the service publishes.
