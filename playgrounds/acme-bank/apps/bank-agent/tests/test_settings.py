"""The environment of the two Aces: through the gateway, and direct."""
import unittest

from settings import ConfigError, Settings

GATEWAY_ENV = {
    "LLM_URL": "http://apim-gateway:8082/acme-bank/llm", "LLM_API_KEY": "acme-ace-llm-key", "LLM_MODEL": "acme-chat",
    "MCP_URL": "http://apim-gateway:8082/acme-bank/mcp", "AM_TOKEN_URL": "http://am-gateway:8092/acme-bank/oauth/token",
    "AGENT_CLIENT_ID": "ace-agent", "AGENT_CLIENT_SECRET": "ace-agent", "DELEGATION": "on",
    "PUBLIC_URL": "http://localhost:8082/acme-bank/ace/", "HTTP_PORT": "8000",
}
DIRECT_ENV = {"LLM_URL": "http://host.docker.internal:11434/v1", "LLM_MODEL": "qwen3:1.7b",
              "MCP_URL": "http://bank-mcp:8000/", "DELEGATION": "off"}


class FromEnv(unittest.TestCase):
    def test_the_ace_behind_the_gateway(self):
        settings = Settings.from_env(GATEWAY_ENV)
        self.assertEqual((settings.llm_url, settings.llm_api_key, settings.llm_model, settings.mcp_url),
                         (GATEWAY_ENV["LLM_URL"], "acme-ace-llm-key", "acme-chat", GATEWAY_ENV["MCP_URL"]))
        self.assertEqual((settings.delegation, settings.am_token_url, settings.agent_client_id),
                         (True, GATEWAY_ENV["AM_TOKEN_URL"], "ace-agent"))
        self.assertEqual((settings.public_url, settings.port), ("http://localhost:8082/acme-bank/ace/", 8000))

    def test_the_direct_ace_needs_no_key_no_identity_and_no_delegation(self):
        settings = Settings.from_env(DIRECT_ENV)
        self.assertEqual((settings.llm_api_key, settings.delegation, settings.am_token_url), ("", False, ""))
        self.assertEqual((settings.public_url, settings.port), ("http://localhost:8000", 8000))

    def test_the_model_thinks_less_unless_told_otherwise(self):
        self.assertEqual(Settings.from_env(DIRECT_ENV).llm_reasoning_effort, "none")
        self.assertEqual(Settings.from_env({**DIRECT_ENV, "LLM_REASONING_EFFORT": "low"}).llm_reasoning_effort, "low")

    def test_a_reasoning_effort_that_is_set_and_empty_is_none_at_all(self):
        """The one setting where empty is not unset: a model that takes no reasoning effort is sent none."""
        for empty in ("", "  "):
            self.assertEqual(Settings.from_env({**DIRECT_ENV, "LLM_REASONING_EFFORT": empty}).llm_reasoning_effort, "")

    def test_it_answers_to_this_machine_unless_told_other_names(self):
        self.assertEqual(Settings.from_env(DIRECT_ENV).allowed_hosts, ("localhost", "127.0.0.1", "[::1]"))
        self.assertEqual(Settings.from_env({**DIRECT_ENV, "ALLOWED_HOSTS": " "}).allowed_hosts, ("localhost", "127.0.0.1", "[::1]"))
        self.assertEqual(Settings.from_env({**DIRECT_ENV, "ALLOWED_HOSTS": " Bank-Agent , localhost,"}).allowed_hosts,
                         ("bank-agent", "localhost"))

    def test_delegation_is_on_unless_it_is_turned_off(self):
        env = {k: v for k, v in GATEWAY_ENV.items() if k != "DELEGATION"}
        self.assertTrue(Settings.from_env(env).delegation)

    def test_an_empty_value_is_an_unset_one(self):
        self.assertEqual(Settings.from_env({**DIRECT_ENV, "LLM_API_KEY": " ", "PUBLIC_URL": ""}).llm_api_key, "")
        with self.assertRaisesRegex(ConfigError, "LLM_URL is not set"):
            Settings.from_env({**DIRECT_ENV, "LLM_URL": ""})

    def test_what_is_missing_is_named(self):
        for name in ("LLM_URL", "LLM_MODEL", "MCP_URL", "AM_TOKEN_URL", "AGENT_CLIENT_ID", "AGENT_CLIENT_SECRET"):
            env = {k: v for k, v in GATEWAY_ENV.items() if k != name}
            with self.assertRaisesRegex(ConfigError, f"{name} is not set"):
                Settings.from_env(env)

    def test_what_is_wrong_is_named(self):
        with self.assertRaisesRegex(ConfigError, "DELEGATION is 'maybe'"):
            Settings.from_env({**DIRECT_ENV, "DELEGATION": "maybe"})
        with self.assertRaisesRegex(ConfigError, "HTTP_PORT is 'http'"):
            Settings.from_env({**DIRECT_ENV, "HTTP_PORT": "http"})


if __name__ == "__main__":
    unittest.main()
