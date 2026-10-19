# AI Agent Inspector

A live sequence diagram of the agent, LLM and MCP traffic that goes through the gateway. Open it on http://localhost:9002.

## Needs

- A license with the feature `apim-reporter-tcp`, which the gateway's TCP reporter uses. The add-on's row says when the license lacks it.
- Internet access for the first start. The image is built from the [Gravitee AI Agent Workshop](https://github.com/gravitee-io-labs/Gravitee-AI-Agent-Workshop) repository, at a fixed commit, so it does not change on its own.

## How it gets the traffic

Starting the add-on recreates the gateway with a TCP reporter, which sends each request and response as a JSON event, and with OpenTelemetry on, which sends the policy details as spans. The inspector receives both inside Docker.

It does not run together with [Gamma Tracing](../gamma-tracing/README.md), or with any add-on of yours that sets the gateway's OpenTelemetry exporter, such as a Jaeger: they all take it. Starting one stops or turns off the others, after saying so.

## Settings

| Setting | Meaning |
|---|---|
| `AGENT_INSPECTOR_PULL_POLICY` | `never` (the default) builds the image here once, `build` builds it at each start, `always` pulls the image that CI builds in `ghcr.io/gravitee-io-labs/gravitee-lab-public-catalog/agent-inspector-agent-inspector` |
