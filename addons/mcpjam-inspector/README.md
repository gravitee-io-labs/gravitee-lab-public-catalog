# MCPJam Inspector

[MCPJam Inspector](https://www.mcpjam.com) connects to MCP servers, calls their tools and chats with them through an LLM. Use it on a server behind the gateway or directly.

## Needs

Nothing more than the platform. To chat with a local model, [Ollama](https://ollama.com) on your machine: the inspector reaches it through the container (see below).

## Ports

| Port | What it is | Login |
|---|---|---|
| 6274 | The inspector. Open it from its link in the Lab, which carries the session token, or on http://localhost:6274 | A session token |

It listens on `127.0.0.1` only.

## Logins and secrets

| What | Value | Setting |
|---|---|---|
| Session token, which signs a browser in from the console link | `gravitee-lab-local-inspector`, a public demo value | `MCPJAM_INSPECTOR_SESSION_TOKEN` |

The token is 24 or more letters, digits, `-` or `_`.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `MCP_INSPECTOR_VERSION` | `3.16.1` | Version of the `@mcpjam/inspector` package |
| `MCPJAM_INSPECTOR_SESSION_TOKEN` | `gravitee-lab-local-inspector` | Token that signs a browser in from the console link |
| `MCPJAM_INSPECTOR_ALLOWED_HOSTS` | empty | Other host names it answers to, comma-separated |
| `MCP_INSPECTOR_PULL_POLICY` | `build` | `build` builds the image at each start, `never` builds it once, `always` pulls the image that CI builds in `ghcr.io/gravitee-io-labs/gravitee-lab-public-catalog/mcp-inspector-mcp-inspector` |

## Good to know

- It runs in a container, built here from the published `@mcpjam/inspector` package. Its local shell and browser tools are off, and it sends no usage reports.
- Its server runs in the container, so `localhost` there is the container itself. To reach a service of the lab, use its name on the Docker network (`http://apim-gateway:8082`), and `host.docker.internal` for a service on your machine.
- MCPJam looks for Ollama on `127.0.0.1:11434`. The container passes that port on to Ollama on your machine, so a model listed in your Ollama is there to chat with.

## What stays after removal

What you save in the inspector, such as the servers you add, lives in the Docker volume `data-mcp-inspector`. Stopping the add-on keeps it, and `make reset` deletes it.
