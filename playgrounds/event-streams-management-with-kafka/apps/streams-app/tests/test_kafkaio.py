import unittest

import kafkaio


class ExplainTest(unittest.TestCase):
    def test_no_certificate_says_the_plan_needs_one(self):
        said = kafkaio.explain(["Disconnected: SSL connection closed by peer"], "anonymous")
        self.assertIn("client certificate", said)
        self.assertIn("mTLS", said)

    def test_a_refused_secret_is_the_ssos_not_the_acls(self):
        self.assertIn("SSO refused", kafkaio.explain(["Failed to retrieve OIDC token from http://am"], "partner", "", "partners"))
        said = kafkaio.explain(["sasl.oauthbearer.method=oidc"], "partner", "Broker: Topic authorization failed", "partners")
        self.assertIn("ACL", said)

    def test_no_token_says_the_sso_is_needed(self):
        said = kafkaio.explain(["Disconnected: SSL connection closed by peer"], "anonymous", host="partners")
        self.assertIn("token of the SSO", said)

    def test_a_rule_of_the_gateway_is_named_as_such(self):
        self.assertIn("rule of the gateway", kafkaio.explain([], "fulfillment", "Broker: Policy violation"))

    def test_an_acl_refusal_says_the_acl(self):
        self.assertIn("ACL", kafkaio.explain([], "partner", "Broker: Topic authorization failed", "partners"))
        self.assertIn("ACL", kafkaio.explain([], "fulfillment", 'KafkaError{code=TOPIC_AUTHORIZATION_FAILED,str="Authorization failed."}'))

    def test_an_existing_topic_is_not_a_failure_of_the_rules(self):
        self.assertIn("exists already", kafkaio.explain([], "fulfillment", "Topic 'orders-eu' already exists."))

    def test_a_closed_connection_is_the_strangers_only(self):
        lines = ["Disconnected: SSL connection closed by peer"]
        self.assertIn("registered", kafkaio.explain(lines, "stranger"))
        self.assertNotIn("registered", kafkaio.explain(lines, "fulfillment", "Local: Broker transport failure"))

    def test_an_untrusted_gateway_names_the_truststore(self):
        self.assertIn("kafka-gateway.crt", kafkaio.explain(["certificate verify failed"], "fulfillment"))

    def test_a_name_that_does_not_resolve_points_to_the_hosts_file(self):
        self.assertIn("hosts file", kafkaio.explain(["Failed to resolve 'orders.kafka.local'"], "fulfillment"))

    def test_nothing_known_keeps_the_clients_own_words(self):
        self.assertEqual(kafkaio.explain([], "fulfillment", "Local: Message timed out"), "Local: Message timed out")


class ConfigTest(unittest.TestCase):
    def setUp(self):
        from settings import load
        self.settings = load({})

    def test_the_gateway_client_presents_its_certificate(self):
        conf = kafkaio.gateway_conf(self.settings, "orders", "fulfillment")
        self.assertEqual(conf["bootstrap.servers"], "orders.kafka.local:9092")
        self.assertEqual(conf["ssl.certificate.location"], "/certs/fulfillment.crt")
        self.assertEqual(conf["security.protocol"], "ssl")

    def test_a_partner_presents_a_token_not_a_certificate(self):
        from settings import load
        conf = kafkaio.gateway_conf(load({"STREAMS_PARTNER_SECRET": "s3"}), "partners", "partner")
        self.assertEqual(conf["security.protocol"], "sasl_ssl")
        self.assertEqual(conf["sasl.mechanisms"], "OAUTHBEARER")
        self.assertEqual(conf["sasl.oauthbearer.client.id"], "partner-portal")
        self.assertNotIn("ssl.certificate.location", conf)

    def test_every_certificate_identity_has_its_own_files(self):
        for who in ("fulfillment", "billing", "stranger"):
            self.assertEqual(kafkaio.gateway_conf(self.settings, "orders", who)["ssl.certificate.location"], f"/certs/{who}.crt")

    def test_the_partners_read_the_orders_topic(self):
        self.assertEqual((kafkaio.topic_of("partners"), kafkaio.topic_of("orders"), kafkaio.topic_of("payments")), ("orders", "orders", "payments"))

    def test_no_certificate_means_none_is_configured(self):
        self.assertNotIn("ssl.certificate.location", kafkaio.gateway_conf(self.settings, "payments", "anonymous"))

    def test_the_broker_client_bypasses_the_gateway(self):
        self.assertEqual(kafkaio.broker_conf(self.settings), {"bootstrap.servers": "kafka:9091", "security.protocol": "plaintext"})

    def test_the_kafka_request_of_the_sni_probe_is_a_well_formed_api_versions_request(self):
        request = kafkaio.api_versions_request()
        self.assertEqual(int.from_bytes(request[:4], "big"), len(request) - 4)
        self.assertEqual(int.from_bytes(request[4:6], "big"), 18)


if __name__ == "__main__":
    unittest.main()
