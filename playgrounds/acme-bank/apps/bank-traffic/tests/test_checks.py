"""How a scenario judges what came back: the expectations, the guard rails, the token count and the outages."""
import unittest

from checks import (DENIED, FAILED, GUARDED, INCONCLUSIVE, OK, PERMITTED, SKIPPED, accepts, all_of, answer_check, blocked_check, instead,
                    outage, same, session_limited, tokens_of, tool_check)
from clients import Reply
from wire import PlatformError


def tool(name, outcome="ok", detail="", **arguments):
    return {"step": "tool", "name": name, "outcome": outcome, "detail": detail, "arguments": arguments}


def hop(step, name, outcome, status=None, detail="it failed"):
    row = {"step": step, "name": name, "outcome": outcome, "detail": detail}
    if status is not None:
        row["status"] = status
    return row


def llm_ok():
    return hop("llm", "acme-chat", "ok", 200.0, "900 tokens, 0 tool call(s)")


def reply(*trace, text="an answer"):
    return Reply(text, list(trace))


GUARD = {"step": "llm", "name": "acme-chat", "outcome": "blocked", "detail": "AI prompt validation"}


class ToolExpectations(unittest.TestCase):
    def test_a_permitted_call_is_ok(self):
        check = tool_check(("list_accounts",), PERMITTED, customer_id="C-1001")
        self.assertEqual(check(reply(tool("list_accounts", customer_id="C-1001"))).status, OK)

    def test_a_denial_that_was_expected_is_ok_and_one_that_was_not_is_a_failure(self):
        self.assertEqual(tool_check(("list_accounts",), DENIED)(reply(tool("list_accounts", "denied"))).status, OK)
        failure = tool_check(("list_accounts",), DENIED)(reply(tool("list_accounts", "ok")))
        self.assertEqual(failure.status, FAILED)
        self.assertIn("came back ok", failure.detail)
        self.assertIn("expected it denied", failure.detail)

    def test_a_permit_that_came_back_denied_is_a_failure(self):
        self.assertEqual(tool_check(("get_balance",), PERMITTED)(reply(tool("get_balance", "denied"))).status, FAILED)

    def test_a_business_error_is_not_a_permit(self):
        check = tool_check(("transfer_funds",), PERMITTED)
        self.assertEqual(check(reply(tool("transfer_funds", "error"))).status, FAILED)

    def test_a_model_that_did_not_call_the_tool_proves_nothing(self):
        result = tool_check(("list_accounts",), DENIED)(reply())
        self.assertEqual(result.status, INCONCLUSIVE)
        self.assertIn("did not call list_accounts", result.detail)

    def test_a_model_that_asked_for_another_account_proves_nothing(self):
        check = tool_check(("list_accounts",), DENIED, customer_id="C-1001")
        self.assertEqual(check(reply(tool("list_accounts", "ok", customer_id="C-2001"))).status, INCONCLUSIVE)

    def test_numbers_are_compared_as_numbers(self):
        check = tool_check(("transfer_funds",), DENIED, amount=600)
        self.assertEqual(check(reply(tool("transfer_funds", "denied", amount=600.0))).status, OK)

    def test_ids_are_compared_without_case_or_spaces(self):
        check = tool_check(("get_balance",), PERMITTED, account_id="ACC-1001")
        self.assertEqual(check(reply(tool("get_balance", account_id=" acc-1001"))).status, OK)

    def test_the_guard_blocking_an_ordinary_question_is_a_failure(self):
        self.assertEqual(tool_check(("get_balance",), PERMITTED)(reply(GUARD)).status, FAILED)


class Guard(unittest.TestCase):
    def test_an_injection_has_to_be_blocked(self):
        self.assertEqual(blocked_check(reply(GUARD)).status, OK)
        self.assertEqual(blocked_check(reply(tool("get_balance"))).status, FAILED)

    def test_an_injection_that_reaches_the_model_is_what_a_switched_off_guard_does_not_a_failure(self):
        found = blocked_check(reply({"step": "llm", "outcome": "ok", "detail": "300 tokens"}))
        self.assertEqual((found.status, found.detail), (OK, "the guard rails are off: the model got it"))

    def test_an_answer_that_repeats_what_the_gateway_masks_says_pii_filtering_is_off(self):
        check = answer_check(forbidden="FR76 3000 6000 0112")
        self.assertEqual(check(reply(text="Your accounts: ...")).detail, "")
        found = check(reply(text="Your IBAN FR7630006000 0112 is fine"))
        self.assertEqual((found.status, found.detail), (OK, "the answer repeats what PII filtering masks: it is off"))
        self.assertEqual(check(reply(text="  ")).status, FAILED)
        self.assertEqual(check(reply(GUARD)).status, FAILED)     # an ordinary question the guard rails stopped is still one

    def test_a_denial_that_became_a_permit_is_what_a_switched_off_policy_engine_does(self):
        check = tool_check(("list_accounts",), GUARDED, customer_id="C-1001")
        for outcome in ("denied", "ok", "error"):
            self.assertEqual(check(reply(tool("list_accounts", outcome, customer_id="C-1001"))).status, OK, outcome)
        self.assertEqual(check(reply(tool("list_accounts", "unauthorized", customer_id="C-1001"))).status, FAILED)
        self.assertEqual(check(reply(tool("list_accounts", "rate_limited", customer_id="C-1001"))).status, SKIPPED)
        self.assertTrue(accepts(GUARDED, "ok") and not accepts(DENIED, "ok") and not accepts(PERMITTED, "denied"))

    def test_a_call_that_went_through_because_the_control_is_off_says_so_and_a_denial_does_not(self):
        """The log of the generator must tell a denial from a EUR 12,000 transfer that went through."""
        check = tool_check(("list_accounts",), GUARDED, customer_id="C-1001")
        said = {outcome: check(reply(tool("list_accounts", outcome, customer_id="C-1001"))).detail for outcome in ("denied", "ok", "error")}
        self.assertEqual(said, {"denied": "", "ok": "went through: the control that decides it is off",
                                "error": "came back with an error: the control that decides it is off, so the bank may have refused it, or may not be answering"})
        self.assertEqual(tool_check(("get_balance",), PERMITTED)(reply(tool("get_balance"))).detail, "")      # a permit is a permit
        self.assertEqual((instead(GUARDED, "denied"), instead(DENIED, "ok"), instead(GUARDED, None)), ("", "", ""))

    def test_a_failure_outranks_an_inconclusive_answer(self):
        def failing(_reply):
            return answer_check()(reply(text="  "))

        vague = tool_check(("get_balance",), PERMITTED)
        self.assertEqual(all_of(vague, failing)(reply()).status, FAILED)
        self.assertEqual(all_of(vague, answer_check())(reply()).status, INCONCLUSIVE)
        self.assertEqual(all_of(answer_check())(reply()).status, OK)


class TokensOfATrace(unittest.TestCase):
    def llm(self, detail, outcome="ok"):
        return {"step": "llm", "outcome": outcome, "detail": detail}

    def test_the_count_is_read_from_the_detail_of_each_model_call(self):
        self.assertEqual(tokens_of([self.llm("934 tokens, 1 tool call(s)"), tool("get_balance"),
                                    self.llm("1,210 tokens, 0 tool call(s)")]), 2144)

    def test_a_trace_without_a_count_is_guessed_per_model_call(self):
        self.assertEqual(tokens_of([self.llm("fine"), self.llm("")]), 1800)

    def test_a_blocked_call_cost_nothing(self):
        self.assertEqual(tokens_of([self.llm("blocked", "blocked")]), 0)

    def test_a_tokens_field_wins(self):
        self.assertEqual(tokens_of([{"step": "llm", "outcome": "ok", "tokens": 321.0, "detail": "999 tokens"}]), 321)


class Outage(unittest.TestCase):
    def test_a_gateway_that_does_not_answer_is_the_platform_not_a_verdict(self):
        with self.assertRaises(PlatformError):
            outage([{"step": "llm", "name": "acme-chat", "status": 504.0}])

    def test_a_denial_is_not_an_outage(self):
        outage([{"step": "tool", "name": "x", "status": 403.0}, {"step": "llm"}])

    def test_a_hop_of_ace_that_did_not_work_at_all_is_the_platform_not_a_verdict(self):
        broken = {
            "a key the LLM plan refuses": (hop("llm", "acme-chat", "error", 401.0, "Unauthorized"),
                                           "Ace's llm acme-chat failed (HTTP 401): Unauthorized", 401),
            "an LLM API that is not deployed": (hop("llm", "acme-chat", "error", 404.0, "HTTP 404"),
                                                "Ace's llm acme-chat failed (HTTP 404): HTTP 404", 404),
            "no connection to the LLM proxy": (hop("llm", "acme-chat", "error", None, "APIConnectionError"),
                                               "Ace's llm acme-chat failed: APIConnectionError", None),
            "a token exchange that AM refused": (hop("exchange", "token-exchange", "error", 401.0, "AM answered 401"),
                                                 "Ace's exchange token-exchange failed (HTTP 401): AM answered 401",
                                                 401),
            "a session the MCP proxy did not open": (hop("tool", "connect", "error", 401.0, "Sign in again."),
                                                     "Ace's tool connect failed (HTTP 401): Sign in again.", 401),
            "a session the MCP proxy refused": (hop("tool", "connect", "denied", 403.0, "Not allowed"),
                                                "Ace's tool connect failed (HTTP 403): Not allowed", 403),
            "a hop that says nothing": (hop("llm", "acme-chat", "error", None, ""),
                                        "Ace's llm acme-chat failed: error", None)}
        for label, (row, message, status) in broken.items():
            with self.subTest(label), self.assertRaises(PlatformError) as caught:
                outage([llm_ok(), row])
            self.assertEqual((str(caught.exception), caught.exception.status), (message, status))

    def test_what_a_policy_decided_is_not_an_outage(self):
        outage([hop("tool", "list_accounts", "denied", 403.0),
                hop("tool", "transfer_funds", "error", 200.0, "Insufficient funds"),
                hop("tool", "get_balance", "rate_limited", 429.0),
                hop("llm", "acme-chat", "blocked", 400.0),
                hop("llm", "acme-chat", "rate_limited", 429.0),
                hop("exchange", "token-exchange", "ok", 200.0),
                hop("tool", "connect", "rate_limited", 429.0)])


class SessionLimited(unittest.TestCase):
    def test_a_session_that_the_proxy_limited_says_so(self):
        found = session_limited([hop("tool", "connect", "rate_limited", 429.0, "Too many requests.")])
        self.assertEqual(found, "Ace's session with the bank's tools was limited: Too many requests.")

    def test_anything_else_is_not_a_limit_of_the_session(self):
        self.assertEqual(session_limited([hop("tool", "get_balance", "rate_limited", 429.0),
                                          hop("llm", "acme-chat", "rate_limited", 429.0),
                                          hop("tool", "connect", "error", 401.0)]), "")


class Same(unittest.TestCase):
    def test_values(self):
        self.assertTrue(same(120.0, 120))
        self.assertFalse(same(121, 120))
        self.assertTrue(same("c-1001 ", "C-1001"))
        self.assertFalse(same(None, "C-1001"))


if __name__ == "__main__":
    unittest.main()
