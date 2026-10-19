"""A check of two READMEs, ACME Bank's and Gamma Tracing's: the commands that clear what Elasticsearch keeps are valid as written."""

import json
import re
import shlex
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACME_BANK = ROOT / "playgrounds" / "acme-bank" / "README.md"
TRACING = ROOT / "addons" / "gamma-tracing" / "README.md"
PARTS = ("entrypoint-request", "entrypoint-response", "endpoint-request", "endpoint-response")


def section(file, title):
    """The text of a `## ` section of a README, up to the next heading."""
    text = file.read_text(encoding="utf-8")
    start = text.index(f"## {title}\n")
    return re.split(r"\n#{1,3} ", text[start + 3:], maxsplit=1)[0]


def commands(text):
    """The `curl` commands of the fenced blocks of a text, as the shell would split them (a quoted body is one word)."""
    return [shlex.split(block.replace("\\\n", " ")) for block in re.findall(r"```\n(curl .*?)\n```", text, flags=re.S)]


def body(command):
    return json.loads(command[command.index("-d") + 1])


class Clearing(unittest.TestCase):

    def setUp(self):
        self.acme_bank = commands(section(ACME_BANK, "Delete the logs"))

    def test_the_logs_have_two_commands_and_the_data_streams_of_tracing_keep_theirs(self):
        self.assertEqual([c[c.index("-X") + 1] for c in self.acme_bank], ["POST", "POST"])
        [stream] = commands(section(TRACING, "What it keeps"))
        self.assertEqual(stream[-1], "http://localhost:9200/_data_stream/traces-apim.otel-default,logs-apim.otel-default")

    def test_the_logs_are_cleared_by_a_query_on_their_daily_indices_which_a_wildcard_delete_would_be_refused_for(self):
        """gravitee-v4-log-* are plain indices (no data stream: `DELETE _data_stream` finds nothing) and Elasticsearch 8 and 9
        refuse a wildcard in a delete of indices (action.destructive_requires_name), so the commands are queries."""
        for command in self.acme_bank:
            with self.subTest(command=command[-3][:60]):
                url = next(word for word in command if word.startswith("http"))
                self.assertRegex(url, r"^http://localhost:9200/gravitee-v4-log-\*/_(update|delete)_by_query\?conflicts=proceed$")
                self.assertNotIn("DELETE", command)
                self.assertEqual(command[command.index("-H") + 1], "Content-Type: application/json")

    def test_the_first_keeps_the_logs_and_drops_the_headers_of_the_four_places_the_gateway_stores_them(self):
        update = next(c for c in self.acme_bank if "_update_by_query" in " ".join(c))
        wanted = body(update)
        self.assertEqual(wanted["query"], {"match_all": {}})
        source = wanted["script"]["source"]
        for part in PARTS:
            self.assertIn(f'"{part}"', source)
        self.assertIn('.remove("headers")', source)
        self.assertNotIn("body", source, "the payloads stay")

    def test_the_second_deletes_the_logs_and_nothing_else(self):
        delete = next(c for c in self.acme_bank if "_delete_by_query" in " ".join(c))
        self.assertEqual(body(delete), {"query": {"match_all": {}}})
        self.assertIn("gravitee-v4-metrics-*", section(ACME_BANK, "Delete the logs"), "the page says the metrics stay")


if __name__ == "__main__":
    unittest.main()
