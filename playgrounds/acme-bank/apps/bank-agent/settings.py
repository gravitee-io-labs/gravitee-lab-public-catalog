"""What Ace is configured with: environment variables only, read once at start."""
import os
from dataclasses import dataclass
from typing import Mapping

DELEGATION_VALUES = {"on": True, "off": False}
LOOPBACK = ("localhost", "127.0.0.1", "[::1]")


class ConfigError(Exception):
    """A setting is missing or wrong: the container says which and stops."""


@dataclass(frozen=True)
class Settings:
    llm_url: str                  # the gateway's LLM proxy, or Ollama's /v1 for the direct Ace
    llm_model: str                # a model alias of the proxy, or a model name for Ollama
    llm_api_key: str              # empty for a model reached directly
    llm_reasoning_effort: str     # what the model is asked for; set to an empty value, it is not asked at all
    mcp_url: str                  # the gateway's MCP proxy, or the bank's MCP server for the direct Ace
    delegation: bool              # act for the user with a token exchanged at AM
    am_token_url: str
    agent_client_id: str
    agent_client_secret: str
    public_url: str               # what clients call, in the agent card
    port: int
    allowed_hosts: tuple[str, ...] = LOOPBACK   # the names it is reached by: a page on another name is refused

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        def read(name: str, default: str = "") -> str:
            return env.get(name, "").strip() or default

        def need(name: str) -> str:
            value = read(name)
            if not value:
                raise ConfigError(f"{name} is not set")
            return value

        delegation = read("DELEGATION", "on")
        if delegation not in DELEGATION_VALUES:
            raise ConfigError(f"DELEGATION is {delegation!r}: use on or off")
        on = DELEGATION_VALUES[delegation]
        port = read("HTTP_PORT", "8000")
        if not port.isdigit():
            raise ConfigError(f"HTTP_PORT is {port!r}: use a port number")
        # The one setting where an empty value is not an unset one: empty sends no reasoning effort at all, for a model
        # that does not take one; unset is "none", which turns the thinking of the local model off
        effort = env.get("LLM_REASONING_EFFORT")
        hosts = tuple(h.strip().lower() for h in read("ALLOWED_HOSTS").split(",") if h.strip())
        return cls(
            llm_url=need("LLM_URL"),
            llm_model=need("LLM_MODEL"),
            llm_api_key=read("LLM_API_KEY"),
            llm_reasoning_effort="none" if effort is None else effort.strip(),
            mcp_url=need("MCP_URL"),
            delegation=on,
            am_token_url=need("AM_TOKEN_URL") if on else read("AM_TOKEN_URL"),
            agent_client_id=need("AGENT_CLIENT_ID") if on else read("AGENT_CLIENT_ID"),
            agent_client_secret=need("AGENT_CLIENT_SECRET") if on else read("AGENT_CLIENT_SECRET"),
            public_url=read("PUBLIC_URL", f"http://localhost:{port}"),
            port=int(port),
            allowed_hosts=hosts or LOOPBACK,
        )
