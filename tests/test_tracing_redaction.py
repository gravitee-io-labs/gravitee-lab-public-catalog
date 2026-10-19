"""What Gamma Tracing masks at the gateway: the credentials of a call, and never the figures of its tokens. ACME Bank's
Tracing pages show how many tokens a model call used (gen_ai.usage.*), so the rule that hides an API key must not hide those.
The gateway matches the whole name of an attribute against the pattern, whatever its case (Java's Matcher.matches() with
CASE_INSENSITIVE); the pattern is read from the add-on's compose file and tried the same way."""

import re
import unittest
from pathlib import Path

import yaml

ADDON = Path(__file__).resolve().parents[1] / "addons" / "gamma-tracing" / "compose.yml"
PREFIX = "gravitee_services_opentelemetry_redactionRules_0_"

# Attributes the gateway exports on spans and OTel log records, with the request and response headers it copies as
# http.request.header.<Name> and http.response.header.<Name>
CREDENTIALS = [
    "gravitee.attribute.api-key", "http.request.header.Authorization", "http.request.header.authorization",
    "http.request.header.Proxy-Authorization", "oauth.token", "oauth.access_token", "oauth.refresh_token", "id_token",
    "http.request.header.X-Auth-Token", "http.request.header.X-Gravitee-Api-Key", "http.request.header.X-API-KEY",
    "http.request.header.apikey", "http.request.header.api_key", "http.request.header.Cookie", "http.response.header.Set-Cookie",
    "oauth.client_secret", "gravitee.attribute.client-secret", "password", "http.request.header.X-Password", "passwd",
    "http.request.header.X-Amz-Credential", "gravitee.attribute.token", "csrf_token",
]
FIGURES = [
    "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens", "gen_ai.usage.total_tokens", "gen_ai.client.token.usage",
    "llmproxy.usage.sent.token", "llmproxy.usage.received.token", "llmproxy.usage.sent.cost",
    "http.response.header.X-Token-Rate-Limit-Limit", "http.response.header.X-Token-Rate-Limit-Remaining",
    "http.response.header.X-Token-Rate-Limit-Reset", "http.response.header.X-Rate-Limit-Remaining",
]
OTHER = [
    "gravitee.api.id", "gravitee.transaction.id", "http.request.header.User-Agent", "http.request.header.Content-Type",
    "http.request.header.Traceparent", "oauth.payload", "oauth.client_id", "jwt", "gen_ai.request.model",
    "gen_ai.tool.name", "gravitee.attribute.llm.kind", "authz_amount", "mcp_tool_name",
]


def gateway_environment():
    compose = yaml.safe_load(ADDON.read_text(encoding="utf-8"))
    return compose["services"]["apim-gateway"]["environment"]


def pattern():
    """The pattern as the gateway compiles it: without its `regex:` prefix, ignoring case."""
    value = gateway_environment()[PREFIX + "attributeNamePattern"]
    assert value.startswith("regex:"), "a pattern without the prefix is a glob"
    return re.compile(value.removeprefix("regex:"), re.IGNORECASE)


def masked(name):
    return pattern().fullmatch(name) is not None


class Redaction(unittest.TestCase):

    def test_every_credential_is_masked(self):
        for name in CREDENTIALS:
            with self.subTest(attribute=name):
                self.assertTrue(masked(name))

    def test_the_figures_of_tokens_are_never_masked(self):
        """A masked number would show as *** in the trace, and the usage of a call would be lost."""
        for name in FIGURES:
            with self.subTest(attribute=name):
                self.assertFalse(masked(name))

    def test_what_is_neither_stays_readable(self):
        for name in OTHER:
            with self.subTest(attribute=name):
                self.assertFalse(masked(name))

    def test_only_a_name_that_says_usage_or_rate_limit_is_spared(self):
        self.assertFalse(masked("gen_ai.usage.input_tokens"))
        self.assertTrue(masked("input_tokens"), "a token that is not counted is a credential")
        self.assertTrue(masked("http.request.header.X-Token"))

    def test_the_masking_is_total_and_the_replacement_is_the_same_for_every_rule(self):
        environment = gateway_environment()
        self.assertEqual(environment[PREFIX + "maskingStrategy_type"], "FULL")
        self.assertEqual(environment["gravitee_services_opentelemetry_redactionDefaultReplacement"], "***")


if __name__ == "__main__":
    unittest.main()
