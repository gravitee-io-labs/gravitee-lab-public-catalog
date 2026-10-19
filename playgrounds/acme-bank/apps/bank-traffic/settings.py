"""What the traffic generator is configured with: environment variables only, read once at start."""
import os
from dataclasses import dataclass
from typing import Mapping

ON, OFF = ("on", "true", "yes", "1"), ("off", "false", "no", "0")
RATE_RANGE = (0.1, 10.0)


class ConfigError(Exception):
    """A setting is missing or wrong: the container says which and stops."""


@dataclass(frozen=True)
class Settings:
    gateway_url: str                 # where the gateway serves the workspace, whose path Gamma gives
    llm_url: str                     # the LLM proxy
    mcp_url: str                     # the MCP proxy, without a trailing slash
    ace_url: str                     # the A2A proxy, with its trailing slash
    am_token_url: str
    client_id: str                   # the AM application of the generator, with the password grant: the A2A plan accepts a token for a subscribed application
    client_secret: str
    password: str                    # of the three users of the cast
    llm_api_key: str                 # the key of the Traffic plan
    apim_url: str                    # the management API: platform users
    gamma_url: str                   # where /gamma is served: the same host as the management API, or another one
    org: str
    env: str
    apim_token: str | None           # a token instead of a login, else apim_login
    apim_login: tuple[str, str] | None
    workspace_name: str
    rate: float                      # 1 is one scenario every two minutes
    enabled: bool                    # false starts paused
    port: int
    protections: bool = False        # the lessons' protections are on (a presenter's start): a denial is expected, not accepted

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        def read(name: str, default: str = "") -> str:
            return env.get(name, "").strip() or default     # empty is unset, as everywhere in the lab

        gateway = read("GATEWAY_URL", "http://apim-gateway:8082").rstrip("/")
        apim = read("APIM_MANAGEMENT_URL", "http://apim-management-api:8083").rstrip("/")
        token, login = read("APIM_TOKEN"), (read("APIM_USERNAME"), read("APIM_PASSWORD"))
        secrets = ("BANK_DEMO_PASSWORD", "TRAFFIC_CLIENT_SECRET", "TRAFFIC_LLM_API_KEY")
        missing = [name for name in secrets if not read(name)]
        if not token and not all(login):
            missing.append("APIM_TOKEN, or APIM_USERNAME and APIM_PASSWORD")
        if missing:
            raise ConfigError("not set: " + ", ".join(missing))
        return cls(
            gateway_url=gateway,
            llm_url=read("LLM_URL", f"{gateway}/acme-bank/llm").rstrip("/"),
            mcp_url=read("MCP_URL", f"{gateway}/acme-bank/mcp").rstrip("/"),
            ace_url=read("ACE_URL", f"{gateway}/acme-bank/ace").rstrip("/") + "/",
            am_token_url=read("AM_TOKEN_URL", "http://am-gateway:8092/acme-bank/oauth/token"),
            client_id=read("TRAFFIC_CLIENT_ID", "acme-bank-traffic"),
            client_secret=read("TRAFFIC_CLIENT_SECRET"),
            password=read("BANK_DEMO_PASSWORD"),
            llm_api_key=read("TRAFFIC_LLM_API_KEY"),
            apim_url=apim,
            gamma_url=read("AIM_GAMMA_URL", apim).rstrip("/"),
            org=read("APIM_ORG", "DEFAULT"),
            env=read("APIM_ENV", "DEFAULT"),
            apim_token=token or None,
            apim_login=None if token else login,
            workspace_name=read("WORKSPACE_NAME", "ACME Bank Teams"),
            rate=rate_of(read("TRAFFIC_RATE", "1")),
            enabled=switch_of(read("TRAFFIC", "on")),
            port=port_of(read("HTTP_PORT", "8000")),
            protections=switch_of(read("PROTECTIONS", "off"), "PROTECTIONS"),
        )


def rate_of(text: str) -> float:
    try:
        rate = float(text)
    except ValueError:
        rate = 0.0
    low, high = RATE_RANGE
    if not low <= rate <= high:
        raise ConfigError(f"TRAFFIC_RATE is {text!r}: use a number from {low:g} to {high:g}")
    return rate


def switch_of(text: str, name: str = "TRAFFIC") -> bool:
    if text.lower() in ON:
        return True
    if text.lower() in OFF:
        return False
    raise ConfigError(f"{name} is {text!r}: use on or off")


def port_of(text: str) -> int:
    if not text.isdigit():
        raise ConfigError(f"HTTP_PORT is {text!r}: use a port number")
    return int(text)
