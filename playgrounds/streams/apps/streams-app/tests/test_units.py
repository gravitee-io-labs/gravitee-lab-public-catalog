import json
import random
import unittest

import orders
import security
import shown
from hub import Hub
from settings import SettingsError, load


class SettingsTest(unittest.TestCase):
    def test_defaults_name_the_lab_services(self):
        settings = load({})
        self.assertEqual(settings.kafka_orders, "orders.kafka.local:9092")
        self.assertEqual(settings.broker, "kafka:9091")
        self.assertIn("localhost", settings.hosts)

    def test_a_bad_port_stops_with_one_line(self):
        with self.assertRaisesRegex(SettingsError, "HTTP_PORT must be a whole number"):
            load({"HTTP_PORT": "eighty"})
        with self.assertRaisesRegex(SettingsError, "between 1 and 65535"):
            load({"HTTP_PORT": "70000"})

    def test_hosts_cannot_be_empty(self):
        with self.assertRaisesRegex(SettingsError, "ALLOWED_HOSTS"):
            load({"ALLOWED_HOSTS": " , "})


class OrdersTest(unittest.TestCase):
    def test_an_order_has_what_the_policies_read(self):
        order = orders.make(rng=random.Random(1))
        self.assertTrue({"orderId", "customer", "email", "country", "amount", "currency", "card", "status"} <= set(order))
        self.assertTrue(order["orderId"].startswith("ORD-"))

    def test_what_is_given_is_kept(self):
        order = orders.make(customer="Léa Martin", country="DE", amount=1500)
        self.assertEqual((order["customer"], order["country"], order["amount"]), ("Léa Martin", "DE", 1500))
        self.assertEqual(order["email"], "lea.martin@example.test")

    def test_ids_do_not_repeat(self):
        ids = {orders.make()["orderId"] for _ in range(50)}
        self.assertEqual(len(ids), 50)

    def test_a_large_order_goes_over_the_offloading_threshold(self):
        size = len(json.dumps(orders.make(large=True)))
        self.assertGreater(size, 100 * 1024)
        self.assertLess(size, 1024 * 1024)       # and under what Kafka accepts without the policy


class ShownTest(unittest.TestCase):
    def test_a_short_value_is_untouched(self):
        self.assertEqual(shown.shorten('{"a": 1}'), '{"a": 1}')

    def test_a_large_order_keeps_its_fields_and_cuts_its_invoice(self):
        text = json.dumps(orders.make(large=True))
        out = json.loads(shown.shorten(text))
        self.assertEqual(out["status"], "CREATED")
        self.assertIn("chars)", out["invoice"])
        self.assertLess(len(json.dumps(out)), shown.LIMIT)

    def test_text_that_is_not_json_is_cut(self):
        self.assertEqual(len(shown.shorten("x" * 5000)), shown.LIMIT + 1)


class HubTest(unittest.TestCase):
    def test_listeners_get_what_is_published_and_the_last_ones_are_kept(self):
        hub = Hub(backlog=2)
        listener = hub.subscribe()
        for n in range(3):
            hub.publish({"n": n})
        self.assertEqual(listener.get_nowait(), {"n": 0})
        self.assertEqual(hub.recent(), [{"n": 1}, {"n": 2}])
        hub.unsubscribe(listener)
        hub.publish({"n": 3})
        self.assertEqual(listener.qsize(), 2)


class SecurityTest(unittest.TestCase):
    def test_host_must_be_one_of_the_allowed(self):
        self.assertTrue(security.host_allowed("localhost:8170", ("localhost",)))
        self.assertFalse(security.host_allowed("evil.example", ("localhost",)))

    def test_a_post_must_be_json_unless_it_is_a_webhook(self):
        self.assertTrue(security.is_json("application/json; charset=utf-8"))
        self.assertFalse(security.is_json("text/plain"))
        self.assertFalse(security.is_json(None))
        self.assertTrue(security.is_json(None, may_be_missing=True))

    def test_a_browser_post_comes_from_the_apps_own_page(self):
        self.assertTrue(security.from_this_page("http://localhost:8170", None, "localhost:8170"))
        self.assertFalse(security.from_this_page("http://evil.example", None, "localhost:8170"))
        self.assertTrue(security.from_this_page(None, None, "streams-app:8000"))
        self.assertFalse(security.from_this_page(None, "cross-site", "localhost:8170"))

    def test_the_page_may_be_framed_by_the_lab_ui_only(self):
        policy = security.hardened()["Content-Security-Policy"]
        self.assertIn("frame-ancestors http://localhost:9000 http://127.0.0.1:9000", policy)
        self.assertNotIn("X-Frame-Options", security.hardened())


if __name__ == "__main__":
    unittest.main()
