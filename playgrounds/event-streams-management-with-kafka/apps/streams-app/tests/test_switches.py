import io
import json
import unittest
from unittest import mock

import switches
from settings import load


class FakeApi:
    """A Management API with the APIs of the switches and Gamma's Explorer connections, answering what the app asks."""

    def __init__(self):
        self.apis = {
            "Orders Events": {"id": "a1", "name": "Orders Events", "state": "STARTED", "deploymentState": "DEPLOYED", "plans": ["kept"],
                              "flows": [{"subscribe": [{"name": "Only high-value orders", "enabled": False}, {"name": "Notification payload", "enabled": False}]}]},
            "Orders Avro": {"id": "v1", "name": "Orders Avro", "state": "STARTED", "deploymentState": "DEPLOYED",
                            "flows": [{"subscribe": [{"name": "Avro to JSON", "enabled": False}]}]},
            "Orders Kafka": {"id": "k1", "name": "Orders Kafka", "state": "STARTED", "deploymentState": "DEPLOYED",
                             "flows": [{"interact": [{"name": "Topic guardrails", "enabled": False}],
                                        "publish": [{"name": "Safe producers", "enabled": False}, {"name": "Byte quota", "enabled": False},
                                                    {"name": "Encrypt card and email", "enabled": False}, {"name": "Offload large orders", "enabled": False}],
                                        "subscribe": [{"name": "Byte quota (read)", "enabled": False}, {"name": "Decrypt card and email", "enabled": False},
                                                      {"name": "Fetch offloaded orders", "enabled": False}, {"name": "Only high-value orders", "enabled": False}]}]},
        }
        self.connections = [{"id": "c0", "name": "Another broker"}, {"id": "c1", "name": "Lab broker"}]
        self.calls = []

    def __call__(self, request, timeout=None):
        path = request.full_url.split("/environments/DEFAULT", 1)[1]
        self.calls.append((request.get_method(), path))
        by_id = {a["id"]: a for a in self.apis.values()}
        if path.startswith("/apis?"):
            body = {"data": [{"id": a["id"], "name": a["name"]} for a in self.apis.values()]}
        elif path.startswith("/modules/esm/kafka-explorer/connections?"):
            body = {"data": self.connections}
        elif request.get_method() == "PUT":
            sent = json.loads(request.data)
            by_id[path.rsplit("/", 1)[1]].update(sent)
            body = {}
        elif path.endswith("/deployments"):
            body = {}
        else:
            body = by_id[path.rsplit("/", 1)[1]]
        return io.BytesIO(json.dumps(body).encode())


class SwitchesTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.management = switches.Management(load({"STREAMS_MANAGEMENT_PASSWORD": "pw"}), opener=self.api)
        patcher = mock.patch.object(switches, "GATEWAY_SYNC_S", 0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_switch_starts_off(self):
        self.assertEqual(set(self.management.states().values()), {False})

    def test_a_switch_turns_all_its_steps_on_and_deploys_once(self):
        self.management.set({"kafka-encrypt": True})
        states = self.management.states()
        self.assertTrue(states["kafka-encrypt"])
        self.assertFalse(states["kafka-offload"])
        posts = [c for c in self.api.calls if c[0] == "POST"]
        self.assertEqual(posts, [("POST", "/apis/k1/deployments")])

    def test_a_switch_with_a_step_on_each_side_turns_both_on(self):
        self.management.set({"quota": True})
        flows = self.api.apis["Orders Kafka"]["flows"][0]
        self.assertTrue(flows["publish"][1]["enabled"] and flows["subscribe"][0]["enabled"])
        self.assertTrue(self.management.states()["quota"])

    def test_the_avro_switch_is_on_its_own_api(self):
        self.management.set({"avro-json": True})
        self.assertTrue(self.management.states()["avro-json"])
        self.assertEqual([c for c in self.api.calls if c[0] == "PUT"], [("PUT", "/apis/v1")])

    def test_two_switches_of_one_api_make_one_update(self):
        self.management.set({"kafka-encrypt": True, "kafka-offload": True})
        self.assertEqual([c for c in self.api.calls if c[0] == "PUT"], [("PUT", "/apis/k1")])

    def test_nothing_changes_nothing_is_deployed(self):
        self.management.set({"kafka-encrypt": False})
        self.assertEqual([c for c in self.api.calls if c[0] in ("PUT", "POST")], [])

    def test_the_update_leaves_out_what_is_read_only(self):
        self.management.set({"http-filter": True})
        sent = [c for c in self.api.calls if c[0] == "PUT"]
        self.assertEqual(sent, [("PUT", "/apis/a1")])
        self.assertNotIn("deploymentState", self.api.apis["Orders Events"].get("sent", {}))

    def test_a_missing_api_is_unavailable_not_a_crash(self):
        del self.api.apis["Orders Events"]
        self.assertIsNone(self.management.states()["http-filter"])

    def test_the_links_name_gamma_the_apis_and_the_explorer_connection(self):
        links = self.management.links(load({}))
        self.assertEqual(links["gamma"], "http://localhost:8086")
        self.assertEqual(links["apis"], {"Orders Events": "a1", "Orders Avro": "v1", "Orders Kafka": "k1"})
        self.assertEqual(links["explorer"], "c1")

    def test_the_links_have_no_explorer_before_the_seed_made_it(self):
        self.api.connections = []
        self.assertIsNone(self.management.links(load({}))["explorer"])


if __name__ == "__main__":
    unittest.main()
