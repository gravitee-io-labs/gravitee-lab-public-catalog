"""Reading what the gateway answers: its message, the wait it announces."""
import json
import unittest
from unittest import mock

from gateway import incoming_transaction, message_of, try_again, wait_seconds


class Messages(unittest.TestCase):
    def test_the_message_of_a_policy(self):
        self.assertEqual(message_of('{"message": "Not allowed", "http_status_code": 403}'), "Not allowed")

    def test_the_message_of_a_json_rpc_error_and_of_a_provider(self):
        rpc = {"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Not allowed by ACME authorization policy"}}
        self.assertEqual(message_of(json.dumps(rpc)), "Not allowed by ACME authorization policy")
        self.assertEqual(message_of({"error": {"message": "model not found", "type": "invalid_request_error"}}),
                         "model not found")

    def test_the_message_of_access_management(self):
        self.assertEqual(message_of({"error": "invalid_grant", "error_description": "Subject token expired"}),
                         "Subject token expired")
        self.assertEqual(message_of({"error": "invalid_client"}), "invalid_client")

    def test_plain_text_is_the_message_and_nothing_is_the_default(self):
        self.assertEqual(message_of("  Bad gateway \n"), "Bad gateway")
        self.assertEqual(message_of("", "no message"), "no message")
        self.assertEqual(message_of(None, "no message"), "no message")
        self.assertEqual(message_of("[1, 2]", "no message"), "no message")
        self.assertEqual(message_of({"http_status_code": 500}, "no message"), "no message")


class Transactions(unittest.TestCase):
    def test_the_transaction_id_of_the_call_that_reached_ace_is_read_when_it_is_a_plain_token(self):
        self.assertEqual(incoming_transaction({"x-gravitee-transaction-id": "3fdb8ff5-ce16-40bf-9b8f-f5ce1630bf4e"}),
                         "3fdb8ff5-ce16-40bf-9b8f-f5ce1630bf4e")
        self.assertEqual(incoming_transaction({"x-gravitee-transaction-id": " abc_1.2 "}), "abc_1.2")

    def test_anything_else_is_left_out_so_that_a_header_cannot_carry_more_than_an_id(self):
        for value in ("", "two words", "a;b", "a\r\nX-Other: 1", "é", "x" * 101):
            self.assertIsNone(incoming_transaction({"x-gravitee-transaction-id": value}), value)
        self.assertIsNone(incoming_transaction({}))


class Waits(unittest.TestCase):
    def test_retry_after_is_in_seconds(self):
        self.assertEqual(wait_seconds({"retry-after": "7"}), 7)

    def test_a_reset_is_an_epoch_in_milliseconds(self):
        with mock.patch("gateway.time") as clock:
            clock.time.return_value = 1000.0
            self.assertEqual(wait_seconds({"x-token-rate-limit-reset": "1007500"}), 8)       # 7.5 s, rounded up
            self.assertEqual(wait_seconds({"x-rate-limit-reset": "1030000"}), 30)
            self.assertEqual(wait_seconds({"x-rate-limit-reset": "999000"}), 1)             # already past: not zero

    def test_no_wait_when_the_gateway_says_nothing_useful(self):
        self.assertIsNone(wait_seconds({}))
        self.assertIsNone(wait_seconds({"x-rate-limit-reset": "-1"}))
        self.assertIsNone(wait_seconds({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT", "x-token-rate-limit-reset": "soon"}))

    def test_the_end_of_a_limit_sentence(self):
        self.assertEqual(try_again(7), " Try again in 7 seconds.")
        self.assertEqual(try_again(1), " Try again in 1 second.")
        self.assertEqual(try_again(None), "")


if __name__ == "__main__":
    unittest.main()
