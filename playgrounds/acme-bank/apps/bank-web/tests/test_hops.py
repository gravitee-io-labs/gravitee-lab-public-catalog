"""The hops of an answer: one anatomy for every call, one naming table, and the evidence of each call (hops.py, answers.py)."""

import unittest
from urllib.parse import parse_qs, urlsplit

import hops
from answers import Answers, evidence
from people import PERSONAS

ALICE = PERSONAS["alice"]
SHAPE = {"kind", "name", "title", "system", "direct", "outcome", "tone", "word", "status", "ms", "summary", "facts", "transaction_id", "request_id", "api"}
IDS = {"transaction_id": "tx-1", "request_id": "req-12345678"}


def rows(trace, gateway=True, **more):
    return hops.rows(trace, person=ALICE, gateway=gateway, **more)


def tool(name="list_accounts", **more):
    return {"step": "tool", "name": name, "outcome": "ok", "status": 200, "ms": 8, **IDS, **more}


def model(**more):
    return {"step": "llm", "name": "acme-chat", "outcome": "ok", "status": 200, "ms": 400, "detail": "1161 tokens, 1 tool call(s)", **IDS, **more}


class TheNamingTable(unittest.TestCase):
    """One title for each kind of hop, "<actor> <verb> <object>": the page, the guide and the README say these words and no others."""

    def test_every_kind_of_hop_has_its_one_title(self):
        found = rows([
            {"step": "exchange", "name": "token-exchange", "outcome": "ok", "status": 200},
            tool("tools/list", detail="8 tools"),
            model(),
            tool("list_accounts"),
            model(detail="1354 tokens, 0 tool call(s)"),
        ])
        self.assertEqual([r["title"] for r in found], [
            "Ace got a token for Alice",
            "Ace asked which tools it may use",
            "Ace asked the model what to do",
            "Ace called list_accounts",
            "Ace asked the model for the answer",
        ])
        self.assertEqual(hops.TITLES["again"], "Ace asked the model again")
        self.assertEqual(hops.asked_ace(ALICE, gateway=True, status=200, ms=5)["title"], "Alice asked Ace")
        self.assertEqual(hops.asked_ace(PERSONAS["tina"], gateway=True, status=200, ms=5)["title"], "Tina asked Ace")
        self.assertEqual(hops.asked_ace(None, gateway=True, status=401, ms=5)["title"], "Someone not signed in asked Ace")
        self.assertEqual(hops.payment(None, "transfer_funds", {}, "unauthorized", hops.NO_TOKEN, gateway=True, status=401, ms=5, **IDS)["title"], "Someone not signed in called transfer_funds",
                         "a call with no token is nobody's, whoever it was meant for")
        paid = hops.payment(ALICE, "transfer_funds", {}, "ok", "done", gateway=True, status=200, ms=5, **IDS)
        self.assertEqual(paid["title"], "Alice called transfer_funds")
        self.assertEqual(hops.workspace({"status": 200}, "Hackathon sandbox")["title"], "Hackathon sandbox asked the AI workspace")
        self.assertEqual(hops.developer({"status": 200})["title"], "A developer asked the model")

    def test_the_model_is_asked_what_to_do_then_again_until_a_tool_has_answered_and_for_the_answer_after_it(self):
        """A model that did not choose a tool the first time and was asked again is asked again: one title never names two different calls. A refused tool
        call answered too."""
        found = rows([model(detail="1 tokens, 0 tool call(s)"), model(), tool("get_balance", outcome="denied", status=403), model(detail="2 tokens, 0 tool call(s)")])
        self.assertEqual([r["title"] for r in found], ["Ace asked the model what to do", "Ace asked the model again", "Ace called get_balance", "Ace asked the model for the answer"])
        titles = [r["title"] for r in rows([model(), model(), model(), tool(), model(), model()])]
        self.assertEqual(titles, ["Ace asked the model what to do", "Ace asked the model again", "Ace asked the model again", "Ace called list_accounts",
                                  "Ace asked the model for the answer", "Ace asked the model for the answer"])

    def test_the_systems_a_call_went_through_are_the_badges_and_a_call_with_no_gateway_says_so(self):
        trace = [{"step": "exchange", "outcome": "ok"}, tool("tools/list"), model(), tool(), model()]
        self.assertEqual([r["system"] for r in rows(trace)], ["Access Management", "MCP proxy", "LLM proxy", "MCP proxy", "LLM proxy"])
        direct = rows(trace, gateway=False)
        self.assertEqual([r["system"] for r in direct], ["Access Management", "No gateway", "No gateway", "No gateway", "No gateway"], "Access Management is never behind the gateway")
        self.assertEqual([r["direct"] for r in direct], [False, True, True, True, True])
        self.assertEqual(hops.asked_ace(ALICE, gateway=True, status=200, ms=1)["system"], "A2A proxy")
        self.assertEqual(hops.asked_ace(ALICE, gateway=False, status=200, ms=1)["system"], "No gateway")
        self.assertEqual(hops.workspace({"status": 200}, "x")["system"], "AI workspace")
        self.assertEqual(hops.developer({"status": 200})["system"], "LLM proxy")

    def test_every_hop_is_the_same_shape_whatever_it_is(self):
        everything = rows([{"step": "exchange"}, tool("tools/list"), tool("connect", outcome="error"), model(), tool(), {"step": "agent", "name": "turn", "outcome": "error"}, {"step": "cache"}])
        everything += [hops.asked_ace(ALICE, gateway=True, status=200, ms=1), hops.payment(ALICE, "transfer_funds", {}, "ok", "", gateway=False, status=200, ms=1, transaction_id=None, request_id=None),
                       hops.workspace({"status": 429, "message": "no"}, "x"), hops.developer({"status": 200, "model": "m", "tokens": {"total": 5}, "cached": True})]
        for found in everything:
            self.assertEqual(set(found), SHAPE, found["title"])
            self.assertIsInstance(found["summary"], str, found["title"])
            self.assertTrue(found["summary"], f"{found['title']}: one line that says what happened")

    def test_a_step_that_is_none_of_the_kinds_is_ace_not_finishing_and_the_connection_that_failed_is_the_list_of_tools(self):
        self.assertEqual(rows([{"step": "agent", "name": "turn", "outcome": "error", "detail": "unexpected error"}])[0]["title"], "Ace could not finish")
        self.assertEqual(rows([{"step": "cache", "name": "x"}])[0]["kind"], "agent")
        connect = rows([tool("connect", outcome="error", status=504, detail="The bank's service did not answer in time.")])[0]
        self.assertEqual((connect["title"], connect["kind"], connect["api"]), ("Ace asked which tools it may use", "tools", "mcp"))
        self.assertEqual(connect["summary"], "Error: The bank's service did not answer in time.")


class WhatHappened(unittest.TestCase):
    def test_a_model_call_says_what_the_model_decided_from_what_follows_it(self):
        found = rows([model(), tool("list_accounts"), tool("get_balance"), model(detail="9 tokens, 0 tool call(s)")])
        self.assertEqual(found[0]["summary"], "The model chose list_accounts and get_balance.")
        self.assertEqual(found[3]["summary"], "The model wrote the answer.")
        self.assertEqual(rows([model(), tool("list_accounts"), model()])[0]["summary"], "The model chose list_accounts.")
        three = rows([model(), tool("a"), tool("b"), tool("c")])[0]["summary"]
        self.assertEqual(three, "The model chose a, b and c.")

    def test_a_model_that_chose_no_tool_and_was_asked_again_is_not_said_to_have_written_the_answer(self):
        found = rows([model(detail="1 tokens, 0 tool call(s)"), model(), tool(), model(detail="2 tokens, 0 tool call(s)")])
        self.assertEqual([r["summary"] for r in found if r["kind"] == "llm"], ["The model chose no tool.", "The model chose list_accounts.", "The model wrote the answer."])
        self.assertEqual(rows([model(detail="1 tokens, 0 tool call(s)")])[0]["summary"], "The model wrote the answer.", "the only call, with no tool: it answered")

    def test_what_ace_may_use_is_said_out_of_the_banks_tools_with_the_missing_ones_named(self):
        every = ["list_accounts", "get_balance", "freeze_card", "transfer_funds"]
        listing = tool("tools/list", detail="3 tools")
        some = rows([listing], offered=["list_accounts", "get_balance", "transfer_funds"], catalog=every)[0]
        self.assertEqual(some["summary"], "Ace may use 3 of 4 tools, not freeze_card.")
        self.assertEqual(some["facts"], [{"label": "Offered", "value": "list_accounts, get_balance, transfer_funds", "code": True}])
        self.assertEqual(rows([listing], offered=every, catalog=every)[0]["summary"], "Ace may use 4 of 4 tools.")
        two = rows([listing], offered=["list_accounts", "get_balance"], catalog=every)[0]["summary"]
        self.assertEqual(two, "Ace may use 2 of 4 tools, not freeze_card and transfer_funds.")
        self.assertEqual(rows([listing], offered=["a", "b"], catalog=None)[0]["summary"], "Ace may use 2 tools.", "no catalog: the count is of what was listed, out of nothing")
        self.assertEqual(rows([listing], offered=["a"], catalog=[])[0]["summary"], "Ace may use 1 tool.")
        self.assertEqual(rows([listing])[0]["summary"], "Ace may use 3 tools.", "Ace did not say which: its own count")
        self.assertEqual(rows([tool("tools/list")])[0]["summary"], "Ace listed the tools.")

    def test_the_call_to_ace_lasted_as_long_as_the_answer_took_and_says_so_in_its_line(self):
        """Its duration holds the calls below it: the line says they are part of it, so that a column of times is not added up."""

        def said(calls):
            return hops.asked_ace(ALICE, gateway=True, status=200, ms=17_700, calls=calls)["summary"]

        self.assertEqual((said(5), said(1), said(0)), ("Ace answered after the 5 calls below.", "Ace answered after the call below.", "Ace answered."))
        refused = hops.asked_ace(ALICE, gateway=True, status=401, ms=40, detail="Unauthorized", calls=0)
        self.assertEqual(refused["summary"], "Unauthorized.")

    def test_the_token_exchange_says_who_the_token_is_for_and_who_acts(self):
        step = {"step": "exchange", "name": "token-exchange", "outcome": "ok", "status": 200, "ms": 12, "detail": "issued: sub = the user, act.sub = ace-agent"}
        claims = {"sub": "x", "act": {"sub": "ace-agent"}}
        issued = rows([step], claims=claims)[0]
        self.assertEqual(issued["summary"], "Access Management issued it: sub Alice, acting agent ace-agent.")
        self.assertEqual((issued["status"], issued["ms"], issued["word"]), (200, 12, "Answered"))
        self.assertEqual(rows([step])[0]["summary"], "issued: sub = the user, act.sub = ace-agent", "without the claims, what Ace said")
        found = rows([step])[0]
        self.assertEqual((found["system"], found["api"], found["request_id"]), ("Access Management", None, None))

    def test_a_token_ace_kept_from_an_earlier_question_is_not_a_call_to_access_management(self):
        """Ace keeps the delegated token until it expires: a hop that said 200 and 0 ms made it look as if Access Management answered every time."""
        step = {"step": "exchange", "name": "token-exchange", "outcome": "ok", "status": 200, "ms": 0, "detail": "reused: sub = the user, act.sub = ace-agent"}
        found = rows([step], claims={"sub": "x", "act": {"sub": "ace-agent"}})[0]
        self.assertEqual(found["summary"], "Ace used the token it got earlier: sub Alice, acting agent ace-agent.")
        self.assertEqual((found["status"], found["ms"], found["word"], found["tone"], found["outcome"]), (None, None, "Reused", "ok", "ok"), "no status and no time to show")
        self.assertEqual(found["title"], "Ace got a token for Alice")
        self.assertEqual(found["system"], "Access Management")

    def test_the_token_holds_whom_it_is_for_who_acts_and_where_it_came_from_behind_one_details(self):
        claims = {"sub": "x", "act": {"sub": "ace-agent"}}
        issued = {"step": "exchange", "outcome": "ok", "status": 200, "ms": 12, "detail": "issued: sub = the user, act.sub = ace-agent"}

        def facts(step):
            return {f["label"]: f["value"] for f in rows([step], claims=claims)[0]["facts"]}

        self.assertEqual(facts(issued), {"Subject": "Alice Martin", "Acting agent": "ace-agent", "Token": "Issued by Access Management for this question"})
        self.assertEqual(facts({**issued, "detail": "reused: sub = the user, act.sub = ace-agent"})["Token"], "Kept from an earlier question, still valid")
        refused = rows([{"step": "exchange", "outcome": "error", "status": 400, "detail": "AM answered 400: invalid_grant"}], claims=claims)[0]
        self.assertEqual((refused["facts"], refused["summary"]), ([], "Error: AM answered 400: invalid_grant"), "a token Access Management refused is a failure, in its words")

    def test_a_call_that_did_not_go_through_says_what_it_was_and_why(self):
        for outcome, status, word in (("denied", 403, "Denied by policy"), ("unauthorized", 401, "Unauthorized"), ("blocked", 400, "Blocked"),
                                      ("rate_limited", 429, "Limited"), ("error", 504, "Error")):
            found = rows([tool("transfer_funds", outcome=outcome, status=status, detail="Not allowed")])[0]
            self.assertEqual((found["word"], found["status"], found["summary"]), (word, status, f"{word}: Not allowed"), outcome)
        self.assertEqual(rows([tool(outcome="denied", detail="")])[0]["summary"], "Denied by policy.")
        self.assertEqual(rows([tool(outcome="unauthorized", detail="Unauthorized")])[0]["summary"], "Unauthorized.", "the reason is not the word said twice")
        self.assertEqual(rows([tool(outcome="something new")])[0]["tone"], "note")
        long = rows([tool(outcome="error", detail="x" * 900)])[0]["summary"]
        self.assertLessEqual(len(long), len("Error: ") + hops.SUMMARY_LIMIT)

    def test_the_status_of_a_call_the_app_made_says_how_it_went(self):
        for status, outcome in ((200, "ok"), (204, "ok"), (400, "blocked"), (401, "unauthorized"), (403, "denied"), (429, "rate_limited"), (500, "error"), (504, "error"), (None, "error")):
            self.assertEqual(hops.outcome_of(status), outcome, status)

    def test_a_tool_holds_what_it_was_asked_and_what_it_answered_and_a_refusal_has_its_reason_in_the_line_only(self):
        ok = rows([tool("get_balance", arguments={"account_id": "ACC-1", "access_token": "x"}, detail='{"balance": 1}')])[0]
        self.assertEqual(ok["facts"], [{"label": "Asked", "value": "account_id ACC-1", "code": True}, {"label": "Result", "value": '{"balance": 1}', "code": True}])
        refused = rows([tool("get_balance", outcome="denied", status=403, arguments={"account_id": "ACC-1"}, detail="Not allowed")])[0]
        self.assertEqual([f["label"] for f in refused["facts"]], ["Asked"], "the reason is said once, in the line")
        self.assertEqual(rows([tool("get_balance", detail="")])[0]["facts"], [], "no arguments and no result: no Details")
        self.assertNotIn("access_token", str(ok))

    def test_a_model_holds_its_name_and_its_tokens_and_a_long_result_is_cut(self):
        found = rows([model(name="acme-chat", detail="1161 tokens, 1 tool call(s)")])[0]
        self.assertEqual(found["facts"], [{"label": "Model", "value": "acme-chat", "code": False}, {"label": "Tokens", "value": "1,161", "code": False}])
        self.assertEqual([f["label"] for f in rows([model(detail="blocked")])[0]["facts"]], ["Model"])
        self.assertLessEqual(len(rows([tool(detail="x" * 1000)])[0]["facts"][-1]["value"]), hops.DETAIL_LIMIT)

    def test_a_workspace_and_a_developer_answer_say_which_model_answered_and_how_many_tokens(self):
        team = hops.workspace({"status": 200, "ms": 900, "model": "smart", "tokens": {"total": 1430}, **IDS}, "Hackathon sandbox")
        self.assertEqual(team["summary"], "The smart model answered, 1,430 tokens.")
        self.assertEqual([f["label"] for f in team["facts"]], ["Model", "Tokens"])
        self.assertEqual((team["kind"], team["api"], team["status"], team["ms"]), ("workspace", "teams", 200, 900))
        cached = hops.developer({"status": 200, "model": "qwen3:1.7b", "cached": True, "tokens": {"total": 0}})
        self.assertEqual(cached["summary"], "The semantic cache answered.")
        # What the gateway refused with is the answer, which the turn shows: the hop says the word and not the sentence again
        limited = hops.developer({"status": 429, "message": "Rate limit exceeded!"})
        self.assertEqual((limited["tone"], limited["summary"]), ("limit", "Limited."))
        self.assertEqual(hops.workspace({"status": 400, "message": "AI prompt validation detected"}, "x")["summary"], "Blocked.")

    def test_numbers_that_crossed_the_wire_as_floats_are_whole_again(self):
        found = rows([tool(ms=12.0, status=200.0)])[0]
        self.assertEqual((found["ms"], found["status"]), (12, 200))
        self.assertEqual((hops.whole("12"), hops.whole(True)), (None, None))

    def test_arguments_are_one_line_and_leave_out_what_looks_like_a_secret(self):
        shown = hops.arguments({"account_id": "ACC-1", "access_token": "x", "Authorization": "y", "api_key": "z", "client_secret": "w"})
        self.assertEqual(shown, "account_id ACC-1")
        self.assertEqual(hops.arguments("not a dict"), "")
        self.assertEqual(hops.arguments({"amount": 600.0, "rate": 4.2, "city": "Paris"}), "amount 600, rate 4.2, city Paris")

    def test_a_trace_that_is_not_a_list_has_no_hops(self):
        self.assertEqual((rows(None), rows({"a": 1}), rows(["x", 1])), ([], [], []))


class TheRequestOfEachHop(unittest.TestCase):
    def test_a_hop_carries_the_request_the_gateway_gave_it_and_the_api_it_went_through(self):
        for step, name, api in (("llm", "acme-chat", "llm"), ("tool", "get_balance", "mcp"), ("tool", "tools/list", "mcp")):
            found = rows([{"step": step, "name": name, **IDS}])[0]
            self.assertEqual((found["request_id"], found["api"], found["transaction_id"]), ("req-12345678", api, "tx-1"), name)
        gate = hops.asked_ace(ALICE, gateway=True, status=200, ms=5, **IDS)
        self.assertEqual((gate["request_id"], gate["api"]), ("req-12345678", "a2a"))
        self.assertEqual(hops.workspace({"status": 200, **IDS}, "x")["api"], "teams")

    def test_a_request_id_the_evidence_route_would_refuse_is_no_id(self):
        for junk in ("x", "a" * 65, "req 12345678", "req-1234\n", "../../etc/passwd", 12345678, None, ["req-12345678"]):
            self.assertIsNone(rows([tool(request_id=junk)])[0]["request_id"], junk)


class TheEvidenceOfEachHop(unittest.TestCase):
    """Every hop that went through the gateway has the Trace and the Logs of its own call; a tool call has its Decisions, a team's call its Spend; the token
    exchange and a call with no gateway have none."""

    def setUp(self):
        self.answers = Answers(now=lambda: 1_791_000_000)

    def evidence(self, row):
        return [(e["kind"], parse_qs(urlsplit(e["url"]).query)) for e in self.answers.hop(row)["evidence"]]

    def test_the_call_to_ace_the_tool_list_and_the_model_have_their_trace_and_their_logs(self):
        story = rows([tool("tools/list", request_id="req-list-0001"), model(request_id="req-model-001"), tool("list_accounts", request_id="req-tool-0001")]) + [
            hops.asked_ace(ALICE, gateway=True, status=200, ms=5, request_id="req-a2a-0001")]
        found = {r["title"]: self.evidence(r) for r in story}
        for title, api, request, kinds in (("Alice asked Ace", "a2a", "req-a2a-0001", ["trace", "logs"]),
                                           ("Ace asked which tools it may use", "mcp", "req-list-0001", ["trace", "logs"]),
                                           ("Ace asked the model what to do", "llm", "req-model-001", ["trace", "logs"]),
                                           ("Ace called list_accounts", "mcp", "req-tool-0001", ["trace", "logs", "decisions"])):
            self.assertEqual([k for k, _ in found[title]], kinds, title)
            for kind, query in found[title]:
                self.assertEqual((query["api"], query["request"]), ([api], [request]), f"{title}: {kind} is of the call beside it and no other")

    def test_a_tool_call_has_its_decision_whether_it_was_refused_or_not_and_the_tool_list_has_none(self):
        """The policy engine decides each tool call: where it did not (its step is off), Gamma has none and the app says so and opens the list."""
        for outcome in ("ok", "denied"):
            self.assertIn("decisions", [k for k, _ in self.evidence(rows([tool(outcome=outcome)])[0])], outcome)
        self.assertNotIn("decisions", [k for k, _ in self.evidence(rows([tool("tools/list")])[0])])
        self.assertNotIn("decisions", [k for k, _ in self.evidence(rows([model()])[0])])

    def test_a_tool_call_the_oauth2_plan_refused_has_no_decision_the_policy_engine_was_never_asked(self):
        """A call with no token, or with one that is no good, is a 401 before the flow: its Trace and its Logs are the gateway's record of it, and Gamma has no decision."""
        refused = hops.payment(None, "transfer_funds", {}, "unauthorized", hops.NO_TOKEN, gateway=True, status=401, ms=5, **IDS)
        self.assertEqual([k for k, _ in self.evidence(refused)], ["trace", "logs"])
        self.assertEqual(refused["summary"], "Unauthorized: no token was sent")
        denied = hops.payment(ALICE, "transfer_funds", {}, "denied", "no", gateway=True, status=403, ms=5, **IDS)
        self.assertEqual([k for k, _ in self.evidence(denied)], ["trace", "logs", "decisions"], "a refusal of the policy engine has its decision")

    def test_the_token_exchange_is_not_behind_the_gateway_and_has_no_evidence(self):
        self.assertEqual(self.answers.hop(rows([{"step": "exchange", "outcome": "ok", "status": 200}])[0])["evidence"], [])

    def test_a_call_with_no_gateway_was_recorded_nowhere_and_has_no_evidence(self):
        for found in rows([tool("tools/list"), model(), tool()], gateway=False):
            self.assertEqual(self.answers.hop({**found, "request_id": None})["evidence"], [], found["title"])

    def test_a_call_without_a_request_id_has_no_link_that_goes_nowhere(self):
        for found in rows([model(request_id=None), tool(request_id=None)]) + [hops.asked_ace(ALICE, gateway=True, status=200, ms=1)]:
            self.assertEqual(self.answers.hop(found)["evidence"], [], found["title"])

    def test_a_teams_call_has_its_trace_its_logs_and_the_spend_of_its_run(self):
        row = hops.workspace({"status": 200, "ms": 800, **IDS}, "Hackathon sandbox")
        self.assertEqual([k for k, _ in self.evidence(row)], ["trace", "logs", "spend"])
        run = self.answers.hop(row, since=1_790_999_000_000)
        spend = next(e for e in run["evidence"] if e["kind"] == "spend")
        self.assertEqual(parse_qs(urlsplit(spend["url"]).query)["since"], ["1790999000000"])
        alone = next(e for e in self.answers.hop(row)["evidence"] if e["kind"] == "spend")
        self.assertEqual(parse_qs(urlsplit(alone["url"]).query)["since"], [str(1_791_000_000_000 - 800)], "no run: from when the call began")
        self.assertNotIn("spend", [k for k, _ in self.evidence(hops.developer({"status": 200, **IDS}))], "a developer's call has no spend")

    def test_the_buttons_come_in_one_order_and_carry_the_labels_the_page_draws(self):
        shuffled = evidence(spend="s", decisions="d", logs="l", trace="t")
        self.assertEqual([(e["kind"], e["label"]) for e in shuffled], [("trace", "Trace"), ("logs", "Logs"), ("decisions", "Decisions"), ("spend", "Spend")])
        self.assertEqual([e["kind"] for e in evidence(decisions="d", trace="t")], ["trace", "decisions"])
        self.assertEqual(evidence(logs=None), [])
        for e in shuffled:
            self.assertEqual(set(e), {"kind", "label", "url"}, "the page needs nothing else: each button is in the hop it opens")


if __name__ == "__main__":
    unittest.main()
