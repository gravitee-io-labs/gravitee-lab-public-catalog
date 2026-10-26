"""How an add-on or a setup describes itself and how an add-on names its settings. The files are read as text."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = sorted([*(ROOT / "addons").glob("*/compose.yml"), *(ROOT / "setups").glob("*.yml")])
VARIABLE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)")
SHARED = {"INTERNAL_API_PASSWORD", "GRAVITEE_LICENSE", "REDIS_PASSWORD"}


def meta(path, key):
    """A line of the x-gravitee block of a file, unquoted."""
    block = path.read_text().split("\nservices:")[0].split("\ninclude:")[0]
    found = re.search(rf"^  {key}: (.*)$", block, re.M)
    if not found:
        return None
    value = found.group(1).strip()
    return value[1:-1] if value[:1] == value[-1:] == '"' else value


class DescriptionTest(unittest.TestCase):
    def test_there_are_items_to_read(self):
        self.assertGreaterEqual(len(ITEMS), 5)

    def test_a_description_starts_with_no_article_and_ends_with_no_period(self):
        for path in ITEMS:
            description = meta(path, "description")
            with self.subTest(path.relative_to(ROOT).as_posix()):
                self.assertTrue(description, "no description")
                self.assertFalse(description.endswith("."), description)
                self.assertNotRegex(description, r"^(?:A|An|The)\s", description)
                self.assertTrue(description[0].isupper(), description)


class SettingsTest(unittest.TestCase):
    """The settings of an add-on are prefixed with its id; the image variables follow the name of their component."""

    PREFIXES = {"mcpjam-inspector": "MCPJAM_INSPECTOR_"}

    def test_these_add_ons_name_their_settings_after_themselves(self):
        for item, prefix in self.PREFIXES.items():
            text = (ROOT / "addons" / item / "compose.yml").read_text()
            for name in sorted(set(VARIABLE.findall(text))):
                with self.subTest(f"{item} {name}"):
                    own = name.startswith(prefix) or name in SHARED or name.endswith(("_REGISTRY", "_VERSION", "_PULL_POLICY"))
                    self.assertTrue(own, f"{name} does not start with {prefix}")

    def test_the_inspector_keeps_the_names_its_package_reads_inside_the_container(self):
        text = (ROOT / "addons/mcpjam-inspector/compose.yml").read_text()
        self.assertRegex(text, r"(?m)^\s+MCPJAM_SESSION_TOKEN: \$\{MCPJAM_INSPECTOR_SESSION_TOKEN:-")
        self.assertRegex(text, r"(?m)^\s+MCPJAM_ALLOWED_HOSTS: \$\{MCPJAM_INSPECTOR_ALLOWED_HOSTS:-")
        self.assertRegex(text, r"#token=\$\{MCPJAM_INSPECTOR_SESSION_TOKEN:-")


if __name__ == "__main__":
    unittest.main()
