# Gravitee public

The default catalog of [Gravitee Lab](https://github.com/gravitee-io-labs/gravitee-lab): playgrounds and add-ons to try the Gravitee platform on your machine.

## What is inside

**Playgrounds**: a use case with its apps, sample data and a guide.

| Playground | What you do | Time |
|---|---|---|
| [ACME Bank](playgrounds/acme-bank/) | Protect an AI agent in production with Gravitee Gamma, one lesson at a time | 35 min |
| [ACME Hotels](playgrounds/acme-hotels/) | Expose, secure and govern an AI agent, its LLM and its MCP tools | 30 min |

**Add-ons**: one capability next to the platform, turned on from the Lab.

| Add-on | What it adds |
|---|---|
| [AI Agent Inspector](addons/agent-inspector/) | Live sequence diagram of the agent, LLM and MCP traffic |
| [Gamma Tracing](addons/gamma-tracing/) | Step-by-step trace of each call through the gateway |
| [Hybrid gateway](addons/hybrid/) | A gateway on your machine, managed by Gravitee Cloud |
| [MCPJam Inspector](addons/mcp-inspector/) | Client for MCP servers, with tool calls and an LLM chat |
| [OpenFGA](addons/openfga/) | Fine-grained authorization server, with its Playground |
| [RedisInsight](addons/redisinsight/) | Browser for the Redis behind rate limits and caches |

**Setups**: several add-ons turned on together. There is none yet.

Each folder has a README with what the item needs, its ports, its logins and secrets, and its settings.

## Use it

A new install of the Lab already lists this catalog, as **Gravitee public**. If it is not there:

1. Open **Library > Catalogs**.
2. Click **Add catalog**.
3. Enter `gravitee-io-labs/gravitee-lab-public-catalog`.
4. Read the preview, then confirm.

From a terminal:

```bash
python3 lab-ui/catalog.py add gravitee-io-labs/gravitee-lab-public-catalog
```

## Contribute

You do not need to ask first: open a pull request. [CONTRIBUTING.md](CONTRIBUTING.md) says how, [REVIEWING.md](REVIEWING.md) is what a maintainer reads, and [SECURITY.md](SECURITY.md) says where to report a problem.

## License

[AGPL-3.0](LICENSE), with the attribution in [NOTICE](NOTICE).
