"""Settings of bank-web: every address and secret comes from the environment, read once at start."""
import os
from dataclasses import dataclass
from typing import Mapping


class ConfigError(Exception):
    """A setting is missing or wrong: the container says which and stops."""


def _split(value: str) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in value.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    web_client_secret: str
    demo_password: str
    web_client_id: str = "acme-bank-web"
    am_token_url: str = "http://am-gateway:8092/acme-bank/oauth/token"            # as this container reaches it: the code is exchanged here
    am_authorize_url: str = "http://localhost:8092/acme-bank/oauth/authorize"     # as the browser reaches it: the login page is Access Management's own
    ace_url: str = "http://apim-gateway:8082/acme-bank/ace/"
    ace_direct_url: str = "http://bank-agent-direct:8000/"
    mcp_url: str = "http://apim-gateway:8082/acme-bank/mcp"
    mcp_direct_url: str = "http://bank-mcp:8000/"
    llm_url: str = "http://apim-gateway:8082/acme-bank/llm"
    gateway_url: str = "http://apim-gateway:8082"
    dev_llm_api_key: str = ""
    admin_token: str = ""
    apim_management_url: str = "http://apim-management-api:8083"
    apim_org: str = "DEFAULT"
    apim_env: str = "DEFAULT"
    apim_username: str = ""
    apim_password: str = ""
    apim_token: str = ""
    gamma_url: str = "http://localhost:8086"
    traffic_url: str = "http://bank-traffic:8000"
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]")
    http_port: int = 8000

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        def read(name: str, default: str = "") -> str:
            return env.get(name, "").strip() or default      # empty is unset, as everywhere in the lab

        missing = [name for name in ("WEB_CLIENT_SECRET", "BANK_DEMO_PASSWORD") if not read(name)]
        if missing:
            raise ConfigError("not set: " + ", ".join(missing))
        port = read("HTTP_PORT", str(cls.http_port))
        if not port.isdecimal():
            raise ConfigError(f"HTTP_PORT is {port!r}: use a port number")
        defaults = cls(web_client_secret="", demo_password="")
        return cls(
            web_client_secret=read("WEB_CLIENT_SECRET"),
            demo_password=read("BANK_DEMO_PASSWORD"),
            web_client_id=read("WEB_CLIENT_ID", defaults.web_client_id),
            am_token_url=read("AM_TOKEN_URL", defaults.am_token_url),
            am_authorize_url=read("AM_AUTHORIZE_URL", defaults.am_authorize_url),
            ace_url=read("ACE_URL", defaults.ace_url),
            ace_direct_url=read("ACE_DIRECT_URL", defaults.ace_direct_url),
            mcp_url=read("MCP_URL", defaults.mcp_url),
            mcp_direct_url=read("MCP_DIRECT_URL", defaults.mcp_direct_url),
            llm_url=read("LLM_URL", defaults.llm_url),
            gateway_url=read("GATEWAY_URL", defaults.gateway_url),
            dev_llm_api_key=read("DEV_LLM_API_KEY"),
            admin_token=read("ADMIN_TOKEN"),
            apim_management_url=read("APIM_MANAGEMENT_URL", defaults.apim_management_url),
            apim_org=read("APIM_ORG", defaults.apim_org),
            apim_env=read("APIM_ENV", defaults.apim_env),
            apim_username=read("APIM_USERNAME"),
            apim_password=read("APIM_PASSWORD"),
            apim_token=read("APIM_TOKEN"),
            gamma_url=read("GAMMA_URL", defaults.gamma_url),
            traffic_url=read("TRAFFIC_URL", defaults.traffic_url),
            allowed_hosts=_split(read("ALLOWED_HOSTS")) or defaults.allowed_hosts,
            http_port=int(port),
        )
