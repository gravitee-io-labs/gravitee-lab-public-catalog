import io
import unittest

import fastavro

import avro
import orders


class AvroTest(unittest.TestCase):
    def test_a_record_starts_with_the_schema_id_the_registry_gave(self):
        value = avro.encode(orders.make(), 7)
        self.assertEqual(value[0], 0)
        self.assertEqual(avro.schema_id_of(value), 7)

    def test_what_follows_the_id_is_the_order_in_avro(self):
        order = orders.make(customer="Léa Martin", country="FR", amount=129.9)
        decoded = fastavro.schemaless_reader(io.BytesIO(avro.encode(order, 1)[5:]), avro.PARSED)
        self.assertEqual((decoded["orderId"], decoded["country"], decoded["amount"]), (order["orderId"], "FR", 129.9))

    def test_json_is_no_avro(self):
        self.assertIsNone(avro.schema_id_of(b'{"orderId": "ORD-1"}'))
        self.assertIsNone(avro.schema_id_of(b""))


if __name__ == "__main__":
    unittest.main()
