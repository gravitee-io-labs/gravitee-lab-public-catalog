"""ACME Hotels' files agree with each other: the logins the Lab UI lists are the defaults of their settings, every
address of Access Management names the domain the seed creates, and the script of the booking filter writes no secret."""

import json
import re
import unittest

import yaml

from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1] / "playgrounds" / "acme-hotels"
SETTING = re.compile(r"\$\{(\w+):-([^}]*)\}")   # ${NAME:-default}


def written(value):
    """What a container gets when nothing sets the setting: its default."""
    return SETTING.sub(lambda m: m.group(2), value)


def default(text, setting):
    return re.search(r"\$\{" + setting + r":-([^}]*)\}", text).group(1)


class Logins(unittest.TestCase):
    """The logins of the playground are what the apps get until a setting is changed."""

    def setUp(self):
        self.text = (FOLDER / "compose.yml").read_text(encoding="utf-8")
        self.accounts = yaml.safe_load(self.text)["x-gravitee"]["accounts"]

    def password(self, username, label):
        found = [a for a in self.accounts if a["username"] == username and label in a["for"]]
        self.assertEqual(len(found), 1, username)
        return written(found[0]["password"])

    def test_the_password_of_the_guest_is_the_default_of_its_setting(self):
        self.assertEqual(self.password("john.doe@gravitee.io", "John Doe"), default(self.text, "ACME_HOTELS_DEMO_PASSWORD"))

    def test_the_passwords_of_the_admin_are_the_defaults_of_their_settings(self):
        self.assertEqual(self.password("admin", "API Management"), default(self.text, "ACME_HOTELS_APIM_PASSWORD"))
        self.assertEqual(self.password("admin", "Access Management"), default(self.text, "ACME_HOTELS_AM_PASSWORD"))

    def test_the_guest_is_the_user_of_the_domain(self):
        domain = yaml.safe_load((FOLDER / "seed/am/domain.yaml").read_text(encoding="utf-8"))
        self.assertEqual([u["username"] for u in domain["users"]], ["john.doe@gravitee.io"])


class Domain(unittest.TestCase):
    """The domain is named once, in its file, and every address that reaches it says so."""

    ADDRESS = re.compile(r"(?:\$\{AM_GATEWAY_URL\}|(?:localhost|am-gateway):8092)/([\w-]+)/")

    def test_every_address_of_the_domain_names_it(self):
        name = yaml.safe_load((FOLDER / "seed/am/domain.yaml").read_text(encoding="utf-8"))["name"]
        files = [FOLDER / "compose.yml", *sorted((FOLDER / "seed/apim/apis").glob("*.json"))]
        found = {path.name: set(self.ADDRESS.findall(path.read_text(encoding="utf-8"))) for path in files}
        for filename, names in found.items():
            with self.subTest(file=filename):
                self.assertLessEqual(names, {name})
        self.assertEqual(set().union(*found.values()), {name})


class BookingFilter(unittest.TestCase):
    """The script that asks Access Management whether a guest may see a booking signs in as the MCP server's client."""

    def script(self):
        api = json.loads((FOLDER / "seed/apim/apis/acme-hotels-api.json").read_text(encoding="utf-8"))
        plan = next(p for p in api["plans"] if p["name"] == "AI Agent")
        return next(s for s in plan["flows"][0]["response"] if s["policy"] == "groovy")["configuration"]["script"]

    def test_it_builds_its_basic_header_from_the_secret_of_the_resource(self):
        script = self.script()
        self.assertIn("${MCP_RESOURCE_SECRET}", script)
        self.assertIn("encodeBase64", script)
        self.assertIsNone(re.search(r"Basic [A-Za-z0-9+/]{8,}={0,2}'", script), "a header written out is a secret in a file")

    def test_the_client_it_signs_in_as_is_the_resource_of_the_seed(self):
        resource = yaml.safe_load((FOLDER / "seed/am/protected-resources/hotel-booking-mcp.yaml").read_text(encoding="utf-8"))
        self.assertIn(f"'{resource['clientId']}:", self.script())
        self.assertEqual(resource["clientSecret"], "${MCP_RESOURCE_SECRET}")


class SharedConfigurations(unittest.TestCase):
    """The endpoints' TLS stores. Since the plugins of API Management 4.12 list "no store" as `NONE`, the Management API
    refuses `{"type": ""}`, which the 4.11 plugins listed: leave a store out to have none."""

    def configurations(self):
        for path in sorted((FOLDER / "seed/apim/apis").glob("*.json")):
            api = json.loads(path.read_text(encoding="utf-8"))["api"]
            for group in api["endpointGroups"]:
                yield path.name, group["name"], group.get("sharedConfiguration")
                for endpoint in group["endpoints"]:
                    yield path.name, endpoint["name"], endpoint.get("sharedConfigurationOverride")

    def test_no_store_has_an_empty_type(self):
        for file, where, configuration in self.configurations():
            ssl = json.loads(configuration or "{}").get("ssl") or {}
            for store in ("keyStore", "trustStore"):
                with self.subTest(file=file, where=where, store=store):
                    self.assertNotEqual((ssl.get(store) or {}).get("type"), "")


if __name__ == "__main__":
    unittest.main()
