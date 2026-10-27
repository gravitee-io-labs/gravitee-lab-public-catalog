import http.client
import json
import threading
import unittest
from pathlib import Path

import server
from hub import Hub
from settings import load
from switches import Management


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = load({"ALLOWED_HOSTS": "localhost,127.0.0.1"})
        app = server.App(settings=settings, assets=server.load_assets(Path(server.__file__).parent / "static"), hub=Hub(10), management=Management(settings))
        cls.httpd = server.Server(("127.0.0.1", 0), app)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def ask(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=body, headers={"Host": f"localhost:{self.port}", **(headers or {})})
        answer = connection.getresponse()
        data = answer.read()
        connection.close()
        return answer.status, dict(answer.getheaders()), data

    def test_health_answers_to_any_host(self):
        status, _, body = self.ask("GET", "/health", headers={"Host": "streams-app:8000"})
        self.assertEqual((status, json.loads(body)), (200, {"status": "ok"}))

    def test_the_page_is_served_and_can_be_framed_by_the_lab_ui_only(self):
        status, headers, body = self.ask("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Event Streams Management with Kafka Demo App", body)
        self.assertIn("frame-ancestors http://localhost:9000", headers["Content-Security-Policy"])
        self.assertNotIn("X-Frame-Options", headers)

    def test_a_look_at_the_headers_gets_the_page_headers_and_no_body(self):
        status, headers, body = self.ask("HEAD", "/")
        self.assertEqual((status, body), (200, b""))
        self.assertIn("frame-ancestors", headers["Content-Security-Policy"])

    def test_an_unknown_host_is_refused(self):
        status, _, _ = self.ask("GET", "/api/config", headers={"Host": "evil.example"})
        self.assertEqual(status, 421)

    def test_the_config_lists_the_switches(self):
        status, _, body = self.ask("GET", "/api/config")
        self.assertEqual(status, 200)
        ids = [s["id"] for s in json.loads(body)["switches"]]
        self.assertEqual(ids, ["http-filter", "http-reshape", "avro-json", "kafka-filter", "kafka-encrypt", "kafka-offload", "guardrails", "safe-producers", "quota"])

    def test_a_webhook_delivery_is_kept_with_its_custom_headers_and_nothing_of_the_gateways(self):
        payload = json.dumps({"id": "ORD-7", "total": 900})
        status, _, _ = self.ask("POST", "/hooks/orders", body=payload, headers={"X-Source": "gateway", "X-Gravitee-Request-Id": "r1"})
        self.assertEqual(status, 200)
        recent = self.httpd.app.hub.recent()
        self.assertEqual(json.loads(recent[-1]["value"])["id"], "ORD-7")
        self.assertEqual(recent[-1]["headers"], [["X-Source", "gateway"]])

    def test_a_post_from_another_page_is_refused(self):
        status, _, _ = self.ask("POST", "/api/clear", body="{}", headers={"Content-Type": "application/json", "Origin": "http://evil.example"})
        self.assertEqual(status, 403)

    def test_a_post_whose_body_is_not_read_leaves_the_connection_ready(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": f"localhost:{self.port}", "Content-Type": "application/json"}
        connection.request("POST", "/api/clear-nothing", body="{}", headers=headers)    # a route that does not exist reads no body
        connection.getresponse().read()
        connection.request("GET", "/health", headers={"Host": f"localhost:{self.port}"})
        answer = connection.getresponse()
        self.assertEqual((answer.status, json.loads(answer.read())), (200, {"status": "ok"}))
        connection.close()

    def test_a_post_that_is_not_json_is_refused(self):
        status, _, _ = self.ask("POST", "/api/clear", body="x", headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)

    def test_an_unknown_channel_is_a_bad_request(self):
        status, _, _ = self.ask("POST", "/api/produce", body=json.dumps({"channel": "carrier-pigeon"}), headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)

    def test_a_topic_name_is_checked_before_it_goes_to_the_gateway(self):
        for body in ({"name": "bad name!", "partitions": 1}, {"name": "ok", "partitions": 500}, {"name": "", "partitions": 1}, {"name": "ok", "partitions": "3"}):
            status, _, _ = self.ask("POST", "/api/topic", body=json.dumps(body), headers={"Content-Type": "application/json"})
            self.assertEqual(status, 400, body)

    def test_the_avro_orders_are_for_the_dashboard_only(self):
        status, _, _ = self.ask("GET", "/api/stream/get?who=france&api=avro")
        self.assertEqual(status, 400)

    def test_a_reader_that_is_nobody_is_a_bad_request(self):
        status, _, _ = self.ask("GET", "/api/stream/sse?who=mallory")
        self.assertEqual(status, 400)

    def test_a_switch_that_does_not_exist_is_a_bad_request(self):
        status, _, _ = self.ask("POST", "/api/switches", body=json.dumps({"wanted": {"nope": True}}), headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
