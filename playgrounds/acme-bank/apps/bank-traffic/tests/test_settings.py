"""What the generator is configured with: environment variables only, read once at start."""
import unittest
from unittest import mock

import server
from settings import ConfigError, Settings
from tests.fakes import ENV


class FromEnvironment(unittest.TestCase):
    def test_what_the_compose_file_sets_is_enough(self):
        settings = Settings.from_env(ENV)
        self.assertEqual((settings.gateway_url, settings.llm_url, settings.mcp_url, settings.ace_url),
                         ("http://gateway", "http://gateway/acme-bank/llm", "http://gateway/acme-bank/mcp",
                          "http://gateway/acme-bank/ace/"))
        self.assertEqual((settings.rate, settings.enabled, settings.port, settings.workspace_name),
                         (1.0, True, 8000, "ACME Bank Teams"))
        self.assertEqual((settings.org, settings.env, settings.gamma_url), ("DEFAULT", "DEFAULT", "http://apim"))
        self.assertEqual(settings.apim_login, ("admin", "admin"))

    def test_the_cast_signs_in_with_the_generators_own_client(self):
        settings = Settings.from_env(ENV)
        self.assertEqual((settings.client_id, settings.client_secret), ("acme-bank-traffic", "traffic-secret"))
        self.assertEqual(Settings.from_env({**ENV, "TRAFFIC_CLIENT_ID": "other"}).client_id, "other")

    def test_the_addresses_of_the_three_proxies_can_be_given(self):
        urls = {"LLM_URL": "http://x/llm/", "MCP_URL": "http://x/mcp/", "ACE_URL": "http://x/ace"}
        settings = Settings.from_env({**ENV, **urls})
        self.assertEqual((settings.llm_url, settings.mcp_url, settings.ace_url),
                         ("http://x/llm", "http://x/mcp", "http://x/ace/"))

    def test_a_token_replaces_the_login_for_the_management_api(self):
        env = {k: v for k, v in ENV.items() if not k.startswith("APIM_U") and k != "APIM_PASSWORD"}
        settings = Settings.from_env({**env, "APIM_TOKEN": "t", "AIM_GAMMA_URL": "http://gamma/"})
        self.assertEqual((settings.apim_token, settings.apim_login, settings.gamma_url), ("t", None, "http://gamma"))

    def test_what_is_missing_is_said_all_at_once(self):
        with self.assertRaises(ConfigError) as caught:
            Settings.from_env({"GATEWAY_URL": "http://gateway"})
        self.assertEqual(str(caught.exception), "not set: BANK_DEMO_PASSWORD, TRAFFIC_CLIENT_SECRET, TRAFFIC_LLM_API_KEY, "
                                                "APIM_TOKEN, or APIM_USERNAME and APIM_PASSWORD")

    def test_an_empty_variable_is_not_set(self):
        with self.assertRaises(ConfigError):
            Settings.from_env({**ENV, "TRAFFIC_LLM_API_KEY": ""})

    def test_traffic_off_starts_paused(self):
        self.assertFalse(Settings.from_env({**ENV, "TRAFFIC": "off"}).enabled)
        self.assertTrue(Settings.from_env({**ENV, "TRAFFIC": "ON"}).enabled)
        with self.assertRaisesRegex(ConfigError, "TRAFFIC is 'maybe'"):
            Settings.from_env({**ENV, "TRAFFIC": "maybe"})

    def test_the_rate_is_a_number_from_a_tenth_to_ten(self):
        self.assertEqual(Settings.from_env({**ENV, "TRAFFIC_RATE": "2.5"}).rate, 2.5)
        for bad in ("0", "11", "fast", "-1"):
            with self.assertRaisesRegex(ConfigError, "TRAFFIC_RATE"):
                Settings.from_env({**ENV, "TRAFFIC_RATE": bad})

    def test_the_port_is_a_number(self):
        self.assertEqual(Settings.from_env({**ENV, "HTTP_PORT": "8123"}).port, 8123)
        with self.assertRaisesRegex(ConfigError, "HTTP_PORT"):
            Settings.from_env({**ENV, "HTTP_PORT": "http"})


class Start(unittest.TestCase):
    def test_a_container_without_its_secrets_stops_and_says_which(self):
        with mock.patch.dict("os.environ", {}, clear=True), self.assertRaises(SystemExit) as stopped:
            server.main()
        self.assertTrue(str(stopped.exception.code).startswith("bank-traffic: not set: BANK_DEMO_PASSWORD"))


if __name__ == "__main__":
    unittest.main()
