# Add-ons

An add-on is one capability on top of the platform, with its own folder and settings; turn it on from the Lab.

| Add-on | What it adds |
|---|---|
| [AI Agent Inspector](agent-inspector/) | Live sequence diagram of the agent, LLM and MCP traffic going through the gateway |
| [Azurite](azurite/) | Azure Blob Storage emulator, the local object store for the gateway's storage resources |
| [Gamma Tracing](gamma-tracing/) | Step-by-step trace of each call through the gateway, in Gamma's Tracing pages |
| [Hybrid gateway](hybrid/) | APIM gateway managed by Gravitee Cloud |
| [Kafka](kafka/) | Kafka broker, Kafka UI, and the gateway's native Kafka entrypoint |
| [MCPJam Inspector](mcp-inspector/) | Client for MCP servers, with tool calls and an LLM chat, via the gateway or directly |
| [OpenFGA](openfga/) | Fine-grained authorization server, with the OpenFGA Playground UI |
| [RedisInsight](redisinsight/) | Browser for the Redis behind rate limits, caches and vector stores |
| [Schema Registry](schema-registry/) | Confluent Schema Registry that keeps the Avro schemas of the Kafka topics |

Every folder has the same README: what it is, what it needs, its ports, its logins and secrets, and its settings. To make your own, see [CONTRIBUTING.md](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/CONTRIBUTING.md).
