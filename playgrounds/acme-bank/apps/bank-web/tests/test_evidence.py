"""The evidence of a call in Gamma: a result links to a route of this app that finds the exact item (the log entry, the trace, the decision, what
the run spent), waits for it where it is not there yet, and says so in a state the page acts on. Nothing the platform says is passed on."""

import base64
import json
import re
from unittest import mock
from urllib.parse import parse_qs, quote, urlsplit

import evidence
from evidence import BadItem, Item, parse, route
from tests.base import AppCase
from tests.fakes import LLM_API, MCP_API, TEAMS_API
from upstream import clean

A2A_API = "00000000-0000-4000-8000-acb200000001"
GAMMA = "http://gamma.test/environments/default"
REQUEST = "5f0e1a52-7c0e-4b3d-9d3a-3f6c2b1a9e01"
OTHER = "6a1f2b63-8d1f-4c4e-8e4b-4a7d3c2b0f12"
EVENT = "d2e11292-0820-4cf4-b0c3-3d64841c6a6b"
TRACE = "5f74ca3237b0f5905018b167f7b93f75"
OTHER_TRACE = "77d84e07a1f94d4eb1a1a06cf0f8b3c4"
STARTED = 1_791_567_074_244          # when the gateway says a request started (ms)


def span(request: str | None, name: str = "POST /acme-bank/mcp", parent: str | None = None) -> dict:
    return {"operationName": name, "attributes": {"gravitee.request.id": request} if request else {}, **({"parentSpanId": parent} if parent else {})}


def trace(trace_id: str, api: str, started: int, request: str | None, *names: str) -> dict:
    """The trace as Gamma has it once the gateway has written all of it: the root span first, then what ran under it."""
    return {"traceId": trace_id, "apiId": api, "startTimeEpochMs": started, "spans": [span(request), *(span(request, n, parent="root") for n in names)]}


def link(kind: str, api: str = "llm", request: str = REQUEST, at: int | None = None, **extra) -> str:
    query = {"kind": kind, "api": api, "request": request, "at": at, **extra}
    return "/api/evidence?" + "&".join(f"{k}={quote(str(v))}" for k, v in query.items() if v is not None)


def decoded(url: str) -> dict:
    raw = parse_qs(urlsplit(url).query)["q"][0]
    return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))


class Looking(AppCase):
    """One look at the platform, as the Lab UI's frame asks for it (`resolve=1`): found, pending, missing or down."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.web.evidence.clock = lambda: self.world.now          # the clock of the test says how long ago a call was
        self.at = int(self.world.now * 1000)

    async def look(self, kind: str, api: str = "llm", request: str = REQUEST, at: int | None = None, **extra) -> dict:
        response = await self.http.get(link(kind, api, request, self.at if at is None else at, **extra) + "&resolve=1", follow_redirects=False)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()

    # -- the log entry --------------------------------------------------------------------------------------------------------
    async def test_the_log_entry_is_the_exact_page_of_the_request_with_the_api_that_served_it(self):
        self.world.apim.record(REQUEST, LLM_API, STARTED)
        self.assertEqual(await self.look("logs"), {"state": "found", "url": f"{GAMMA}/aim/observe/logs/{REQUEST}?apiId={LLM_API}"})
        self.assertEqual(self.world.apim.log_reads, [(REQUEST, LLM_API)])
        self.assertEqual(self.world.apim.searches, [], "no search: the entry is read by its id")

    async def test_each_api_is_asked_for_by_its_own_id(self):
        for api, api_id in (("a2a", A2A_API), ("llm", LLM_API), ("mcp", MCP_API), ("teams", TEAMS_API)):
            self.world.apim.record(REQUEST, api_id, STARTED)
            found = await self.look("logs", api)
            self.assertEqual(found["url"], f"{GAMMA}/aim/observe/logs/{REQUEST}?apiId={api_id}", api)
            self.world.apim.gateway_logs.clear()

    async def test_an_entry_that_is_not_there_yet_is_pending_for_a_while_and_then_missing_with_its_list_instead(self):
        self.assertEqual(await self.look("logs"), {"state": "pending"})
        self.world.now += evidence.GRACE["logs"] - 1
        self.assertEqual(await self.look("logs"), {"state": "pending"})
        self.world.now += 2
        missing = await self.look("logs")
        self.assertEqual(missing["state"], "missing")
        self.assertTrue(missing["url"].startswith(f"{GAMMA}/aim/observe/logs?q="), "the list, not a page of Gamma that says it found nothing")
        query = decoded(missing["url"])
        self.assertEqual(query["c"], [{"field": "REQUEST_ID", "label": "Request ID", "operator": "eq", "value": [REQUEST]}])
        self.assertEqual(query["t"], {"type": "absolute", "from": self.at - evidence.BEFORE, "to": self.at + evidence.AFTER}, "a window that does not empty")

    async def test_how_long_an_item_is_waited_for_is_pinned_for_each_kind(self):
        """A grace too long keeps a call that Gamma never recorded 'pending' for ever; one too short gives up on an item that is on its way."""
        self.assertEqual(evidence.GRACE, {"logs": 25, "trace": 25, "decisions": 15, "spend": 25})
        for kind, api in (("logs", "llm"), ("trace", "mcp"), ("decisions", "mcp"), ("spend", "teams")):
            grace = evidence.GRACE[kind]
            self.world.now = self.at / 1000 + grace - .5
            self.assertEqual((await self.look(kind, api))["state"], "pending", f"{kind} just inside {grace} s")
            self.world.now = self.at / 1000 + grace + .5
            self.assertEqual((await self.look(kind, api))["state"], "missing", f"{kind} just after {grace} s")
        self.world.now = self.at / 1000
        self.assertEqual((await self.look("logs", "llm", at=self.at + 30_000))["state"], "missing", "a call that is said to be later than now has nothing to wait for")

    async def test_the_first_second_of_an_entry_has_its_ids_and_nothing_else_and_Gamma_would_show_nothing_of_it(self):
        self.world.apim.record(REQUEST, LLM_API, STARTED, status=None, uri=None)
        self.assertEqual(await self.look("logs"), {"state": "pending"})
        self.world.apim.record(REQUEST, LLM_API, STARTED, status=200)
        self.assertEqual((await self.look("logs"))["state"], "found")

    async def test_an_entry_of_another_api_is_not_the_entry(self):
        self.world.apim.record(REQUEST, MCP_API, STARTED)
        self.assertEqual(await self.look("logs", "llm"), {"state": "pending"})

    async def test_an_api_the_platform_does_not_name_is_no_api_to_look_in_and_is_asked_for_again_at_once_not_after_the_wait(self):
        self.world.apim.apis = []
        self.world.apim.record(REQUEST, MCP_API, STARTED)
        self.assertEqual(await self.look("logs", "mcp"), {"state": "down"})
        self.world.apim.apis = [{"id": MCP_API, "name": "ACME Bank MCP", "type": "MCP_PROXY"}]           # made again since
        self.assertEqual((await self.look("logs", "mcp"))["state"], "found")

    # -- the trace ------------------------------------------------------------------------------------------------------------
    async def test_the_trace_is_the_one_that_started_with_the_request_and_whose_spans_name_it(self):
        self.world.apim.record(REQUEST, MCP_API, STARTED)
        self.world.apim.traces = [
            trace(OTHER_TRACE, MCP_API, STARTED + 4, OTHER, "tools/call"),           # started at the same moment, for another request
            trace(TRACE, MCP_API, STARTED + 1, REQUEST, "tools/call"),
            trace("a" * 32, MCP_API, STARTED + 4000, REQUEST),                       # the same request in another trace's time: not one that started with it
            trace("b" * 32, A2A_API, STARTED, REQUEST)]                              # another API's
        self.assertEqual(await self.look("trace", "mcp"), {"state": "found", "url": f"{GAMMA}/aim/observe/tracing/{MCP_API}/{TRACE}"})
        search = self.world.apim.trace_searches[0]
        self.assertEqual(search["body"]["apiId"], MCP_API)
        self.assertEqual(search["body"]["timeRange"], {"from": evidence.stamp(STARTED - 2000), "to": evidence.stamp(STARTED + 3000)}, "a few seconds around the start the log gives")
        self.assertEqual(search["query"], {"page": "1", "perPage": "100"})

    async def test_the_trace_of_a_slow_call_is_found_though_it_started_a_second_after_the_log(self):
        """The request id on the spans is what proves a trace is the call's, so a trace that started up to two seconds after the log entry of a slow call is read,
        the closest first."""
        self.world.apim.record(REQUEST, MCP_API, STARTED)
        self.world.apim.traces = [trace(OTHER_TRACE, MCP_API, STARTED + 100, OTHER, "tools/call"), trace(TRACE, MCP_API, STARTED + 761, REQUEST, "tools/call")]
        self.assertEqual(await self.look("trace", "mcp"), {"state": "found", "url": f"{GAMMA}/aim/observe/tracing/{MCP_API}/{TRACE}"})
        self.world.apim.traces = [trace(TRACE, MCP_API, STARTED + evidence.START + 1, REQUEST, "tools/call")]
        self.assertEqual((await self.look("trace", "mcp"))["state"], "pending", "apart from the request by more than that: not read")

    async def test_a_trace_is_the_calls_once_its_root_span_is_written_not_before(self):
        """The gateway writes the spans as they end and the root ends last: a trace opened with part of its spans shows part of the call
        (a long team answer, a moment after it) and Gamma does not read it again."""
        self.world.apim.record(REQUEST, TEAMS_API, STARTED)
        whole = trace(TRACE, TEAMS_API, STARTED, REQUEST, "REQUEST Security", "Request phase", "policy-cost-ratelimit")
        self.world.apim.traces = [{**whole, "spans": whole["spans"][1:]}]                    # the children have ended, the root has not
        self.assertEqual(await self.look("trace", "teams"), {"state": "pending"})
        self.world.apim.traces = [whole]
        self.assertEqual((await self.look("trace", "teams"))["url"], f"{GAMMA}/aim/observe/tracing/{TEAMS_API}/{TRACE}")
        self.world.apim.traces = [{**whole, "spans": [{**s, "attributes": {}} for s in whole["spans"]]}]
        self.assertEqual((await self.look("trace", "teams"))["state"], "pending", "a whole trace of another request is not the call's")
        self.world.apim.traces = [{**whole, "spans": [whole["spans"][0], "junk", None, {"parentSpanId": 5}]}]
        self.assertEqual((await self.look("trace", "teams"))["state"], "found", "what is not a span is not read")
        self.world.apim.traces = [{**whole, "spans": "no spans"}]
        self.assertEqual((await self.look("trace", "teams"))["state"], "pending")

    async def test_the_trace_is_looked_for_only_once_the_log_gave_the_moment_and_waited_for_while_none_names_the_request(self):
        self.assertEqual(await self.look("trace", "mcp"), {"state": "pending"})
        self.assertEqual(self.world.apim.trace_searches, [], "no moment, no search")
        self.world.apim.record(REQUEST, MCP_API, STARTED)
        self.world.apim.traces = [trace(OTHER_TRACE, MCP_API, STARTED, OTHER)]
        self.assertEqual(await self.look("trace", "mcp"), {"state": "pending"})
        self.world.now += evidence.GRACE["trace"] + 1
        missing = await self.look("trace", "mcp")
        self.assertEqual(missing["state"], "missing")
        self.assertTrue(missing["url"].startswith(f"{GAMMA}/aim/observe/tracing/{MCP_API}?q="), "the traces of that API around the call")
        self.assertEqual(decoded(missing["url"])["t"], {"type": "absolute", "from": self.at - evidence.BEFORE, "to": self.at + evidence.AFTER})

    async def test_a_hundred_traces_at_the_same_moment_read_only_the_closest_few(self):
        """The search lists up to a hundred: each one read is a call of the admin account."""
        self.world.apim.record(REQUEST, MCP_API, STARTED)
        self.world.apim.traces = [trace(f"{n:032x}", MCP_API, STARTED + n % 50, OTHER) for n in range(1, 101)] + [trace(TRACE, MCP_API, STARTED, REQUEST)]
        found = await self.look("trace", "mcp")
        self.assertEqual(found["state"], "found")
        self.assertLessEqual(len(self.world.apim.trace_reads), evidence.CANDIDATES)

    async def test_the_candidates_are_five_at_most_and_none_that_started_apart_from_the_request_is_read(self):
        """Each trace read is a call of the admin account, and the request id on the spans is what proves a trace is the call's: only those that started with it are asked for."""
        self.assertEqual((evidence.CANDIDATES, evidence.START), (5, 2000))
        self.world.apim.record(REQUEST, MCP_API, STARTED)
        self.world.apim.traces = [trace(f"{n:032x}", MCP_API, STARTED + n % 50, OTHER) for n in range(1, 21)]                 # twenty that started with it, none its own
        self.assertEqual((await self.look("trace", "mcp"))["state"], "pending")
        self.assertEqual(len(self.world.apim.trace_reads), 5, "the five closest, no more")
        self.world.apim.trace_reads.clear()
        self.world.apim.traces = [trace(f"{n:032x}", MCP_API, STARTED + evidence.START + n, REQUEST) for n in range(1, 21)] + [trace("c" * 32, MCP_API, STARTED - evidence.START - 1, REQUEST)]
        self.assertEqual((await self.look("trace", "mcp"))["state"], "pending", "a trace that started after the request, even one that names it, is not the call's")
        self.assertEqual(self.world.apim.trace_reads, [], "none of them is read: they did not start with the request")
        self.world.apim.traces = [trace(TRACE, MCP_API, STARTED + evidence.START, REQUEST), trace("d" * 32, MCP_API, STARTED - evidence.START, OTHER)]
        self.assertEqual((await self.look("trace", "mcp"))["state"], "found", "the edge of what started with it is still with it")

    async def test_a_trace_with_an_id_that_is_not_one_is_not_used_to_build_a_link(self):
        self.world.apim.record(REQUEST, MCP_API, STARTED)
        self.world.apim.traces = [trace("../../admin", MCP_API, STARTED, REQUEST)]
        self.assertEqual(await self.look("trace", "mcp"), {"state": "pending"})

    async def test_a_workspace_that_records_no_trace_ends_on_the_list_of_its_traces(self):
        self.world.apim.record(REQUEST, TEAMS_API, STARTED)
        self.world.now += evidence.GRACE["trace"] + 1
        self.assertEqual((await self.look("trace", "teams"))["url"][:len(f"{GAMMA}/aim/observe/tracing/{TEAMS_API}?q=")], f"{GAMMA}/aim/observe/tracing/{TEAMS_API}?q=")

    # -- the decision ---------------------------------------------------------------------------------------------------------
    async def test_the_decision_is_the_page_of_its_event_and_is_found_by_the_request_it_was_about(self):
        self.world.apim.decide(OTHER, "e" * 36)
        self.world.apim.decide(REQUEST, EVENT)
        found = await self.look("decisions", "mcp")
        self.assertEqual(found, {"state": "found", "url": f"{GAMMA}/authz/observe/logs/{EVENT}?apiId={MCP_API}"})
        body = self.world.apim.decision_searches[0]["body"]
        self.assertEqual(body["filters"], [{"name": "RECORD_TYPE", "operator": "EQ", "value": "AUTHZ_DECISION"}, {"name": "REQUEST_ID", "operator": "EQ", "value": REQUEST}])
        self.assertLess(body["timeRange"]["from"], body["timeRange"]["to"])

    async def test_a_decision_that_is_not_filed_yet_is_pending_and_then_missing_with_the_decisions_of_that_request(self):
        self.world.apim.decide(OTHER, EVENT)
        self.assertEqual(await self.look("decisions", "mcp"), {"state": "pending"})
        self.world.now += evidence.GRACE["decisions"] + 1
        missing = await self.look("decisions", "mcp")
        self.assertEqual(missing["state"], "missing")
        self.assertTrue(missing["url"].startswith(f"{GAMMA}/authz/observe/logs?q="))
        self.assertEqual(decoded(missing["url"])["c"][0]["value"], [REQUEST])

    async def test_a_search_that_answers_with_the_decision_of_another_request_has_not_found_this_ones(self):
        self.world.apim.search_filters = False
        self.world.apim.decide(OTHER, EVENT)
        self.assertEqual(await self.look("decisions", "mcp"), {"state": "pending"})
        self.world.apim.decide(REQUEST, "e" * 36)
        self.assertEqual((await self.look("decisions", "mcp"))["url"], f"{GAMMA}/authz/observe/logs/{'e' * 36}?apiId={MCP_API}")

    async def test_a_record_that_is_not_for_this_request_or_has_no_usable_id_is_never_the_decision(self):
        for event, api in (("../../x", MCP_API), (EVENT, "a/b"), (None, MCP_API), ("short", MCP_API)):
            self.world.apim.decisions.clear()
            self.world.apim.decide(REQUEST, event, api_id=api)
            self.assertEqual((await self.look("decisions", "mcp"))["state"], "pending", (event, api))
        self.world.apim.decisions[:] = ["junk", {"requestId": REQUEST}]
        self.assertEqual((await self.look("decisions", "mcp"))["state"], "pending")

    # -- what a run spent -----------------------------------------------------------------------------------------------------
    async def test_what_a_run_spent_is_the_dashboard_of_the_workspace_for_that_person_and_that_window(self):
        self.world.apim.record(REQUEST, TEAMS_API, self.at - 3_000, applicationId="894d9de3-24a3-4e2f-8d9d-e324a3de2f91")      # the last call of the run
        found = await self.look("spend", "teams", since=self.at - 25_000)
        self.assertEqual(found["state"], "found")
        self.assertTrue(found["url"].startswith(f"{GAMMA}/aim/observe/dashboards/ai-workspace-overview?q="), found["url"])
        query = decoded(found["url"])
        self.assertEqual([(c["field"], c["value"]) for c in query["c"]], [("API_PRODUCT", ["ws-1"]), ("APPLICATION", ["894d9de3-24a3-4e2f-8d9d-e324a3de2f91"])])
        self.assertEqual(query["t"], {"type": "absolute", "from": self.at - 25_000 - evidence.RUN_BEFORE, "to": self.at + evidence.AFTER // 6})

    async def test_the_window_of_a_spend_holds_the_whole_call_whatever_it_took(self):
        """The link is made after the call: a window that began a few seconds before it would miss a call that took longer, and the dashboard would show nothing."""
        for took in (300, 4_700, 14_000, 40_000, 590_000):
            self.world.apim.gateway_logs.clear()
            self.world.apim.record(REQUEST, TEAMS_API, self.at - took, applicationId=None)           # the gateway says when the call began
            for since in (None, self.at - took):                                                      # the link carries it, or does not
                found = decoded((await self.look("spend", "teams", **({"since": since} if since else {})))["url"])["t"]
                self.assertLessEqual(found["from"], self.at - took, f"a call of {took} ms, since {since}")
                self.assertGreaterEqual(found["to"], self.at, f"a call of {took} ms, since {since}")
                self.assertLessEqual(self.at - found["from"], took + evidence.RUN_BEFORE, "and not a window of the whole day")

    async def test_the_window_of_a_spend_opens_at_the_earlier_of_what_the_link_carries_and_what_the_log_says(self):
        self.world.apim.record(REQUEST, TEAMS_API, self.at - 9_000, applicationId=None)
        self.assertEqual(decoded((await self.look("spend", "teams", since=self.at - 6_000))["url"])["t"]["from"], self.at - 9_000 - evidence.RUN_BEFORE, "the log began earlier")
        self.assertEqual(decoded((await self.look("spend", "teams", since=self.at - 20_000))["url"])["t"]["from"], self.at - 20_000 - evidence.RUN_BEFORE, "the run began earlier")
        for odd in (None, "x", True, 1.5):
            self.world.apim.record(REQUEST, TEAMS_API, odd, applicationId=None)
            self.assertEqual(decoded((await self.look("spend", "teams", since=self.at - 6_000))["url"])["t"]["from"], self.at - 6_000 - evidence.RUN_BEFORE, f"a log that gives {odd!r}")

    async def test_a_single_answer_has_its_spend_from_its_own_start_and_a_person_the_log_does_not_name_is_the_workspace(self):
        self.world.apim.record(REQUEST, TEAMS_API, self.at - 4_700, applicationId=None)
        query = decoded((await self.look("spend", "teams"))["url"])
        self.assertEqual([c["field"] for c in query["c"]], ["API_PRODUCT"])
        self.assertEqual(query["t"]["from"], self.at - 4_700 - evidence.RUN_BEFORE)

    async def test_the_workspace_of_a_spend_is_the_one_the_platform_has_now_not_the_one_read_at_start(self):
        self.world.apim.record(REQUEST, TEAMS_API, self.at - 2_000, applicationId=None)
        self.web.keys.workspace = {"id": "ws-old"}                           # read before a re-seed made the workspace again
        query = decoded((await self.look("spend", "teams"))["url"])
        self.assertEqual(query["c"][0]["value"], ["ws-1"])

    async def test_the_spend_waits_for_the_log_of_the_last_call_which_is_when_the_dashboard_has_the_run_and_ends_on_the_workspaces_page(self):
        self.assertEqual(await self.look("spend", "teams"), {"state": "pending"})
        self.world.now += evidence.GRACE["spend"] + 1
        self.assertEqual(await self.look("spend", "teams"), {"state": "missing", "url": f"{GAMMA}/aim/ai-workspaces/ws-1/spend"})

    # -- the platform does not answer -----------------------------------------------------------------------------------------
    async def test_a_platform_that_does_not_answer_is_down_and_gives_no_address_of_a_page_that_would_not_open(self):
        self.world.transport.hosts.pop("apim.test")
        for kind, api in (("logs", "llm"), ("trace", "llm"), ("decisions", "mcp"), ("spend", "teams")):
            self.assertEqual(await self.look(kind, api), {"state": "down"}, kind)

    async def test_a_platform_that_says_what_it_should_not_has_it_said_to_the_log_and_not_to_the_page(self):
        self.world.apim.down.add("llm")
        self.world.apim.page_for_errors = "Traceback (most recent call last): java.lang.IllegalStateException at internal-es-01.corp:9200"
        self.world.transport.hosts.pop("apim.test")
        with self.assertLogs("bank-web.evidence", level="INFO"):
            answer = await self.http.get(link("logs", at=self.at) + "&resolve=1")
        self.assertEqual(answer.json(), {"state": "down"})
        self.assertNotIn("internal", answer.text)

    async def test_a_platform_that_takes_too_long_is_down_after_a_short_while(self):
        self.world.apim.record(REQUEST, LLM_API, STARTED)
        self.world.apim.delay = 1.0
        with mock.patch.object(evidence, "PASS", 0.05):
            self.assertEqual(await self.look("logs"), {"state": "down"})

    async def test_credentials_the_platform_refuses_are_down_too(self):
        self.world.apim.record(REQUEST, LLM_API, STARTED)
        with mock.patch.object(self.web.evidence.management, "_auth", ("admin", "wrong")):
            self.assertEqual(await self.look("logs"), {"state": "down"})

    # -- an API made again --------------------------------------------------------------------------------------------------------
    NEW_MCP = "9c1f7a52-7c0e-4b3d-9d3a-3f6c2b1a9e77"

    async def test_an_api_made_again_with_another_id_is_looked_in_by_its_new_id_once_the_platform_answers_404_for_the_first(self):
        """A re-seed makes the MCP proxy and the workspace again: the id read before it must not stay for good, or every evidence would end 'pending' and then 'missing'."""
        self.world.apim.record(REQUEST, MCP_API, STARTED)
        self.assertEqual((await self.look("logs", "mcp"))["url"], f"{GAMMA}/aim/observe/logs/{REQUEST}?apiId={MCP_API}")
        self.world.apim.gone.add(MCP_API)
        self.world.apim.apis = [{"id": self.NEW_MCP, "name": "ACME Bank MCP", "type": "MCP_PROXY"}]
        self.world.apim.record(OTHER, self.NEW_MCP, STARTED)
        self.assertEqual(await self.look("logs", "mcp", request=OTHER), {"state": "found", "url": f"{GAMMA}/aim/observe/logs/{OTHER}?apiId={self.NEW_MCP}"})
        self.world.apim.traces = [trace(TRACE, self.NEW_MCP, STARTED, OTHER, "tools/call")]
        self.assertEqual((await self.look("trace", "mcp", request=OTHER))["url"], f"{GAMMA}/aim/observe/tracing/{self.NEW_MCP}/{TRACE}")
        self.assertEqual(await self.web.apis.id("mcp"), self.NEW_MCP, "and it is the one the page asks for from now on")

    async def test_an_item_that_is_only_not_there_yet_does_not_make_the_app_read_the_id_of_its_api_again(self):
        self.world.apim.record(REQUEST, MCP_API, STARTED)
        await self.look("logs", "mcp")

        def reads():
            return [p for p in self.world.apim.log if p.endswith("/apis")]

        before = len(reads())
        for _ in range(4):
            self.assertEqual((await self.look("logs", "mcp", request=OTHER))["state"], "pending")
        self.assertEqual(len(reads()), before, "the API is there: only the entry is not")

    async def test_a_platform_that_cannot_say_whether_the_api_is_there_does_not_make_the_id_forgotten(self):
        self.world.apim.record(REQUEST, MCP_API, STARTED)
        await self.look("logs", "mcp")
        self.world.apim.down.add("mcp")                                         # the API's own page answers 503
        self.assertEqual((await self.look("logs", "mcp", request=OTHER))["state"], "pending")
        self.assertEqual(self.web.apis._found["mcp"], MCP_API)
        self.assertTrue(await self.web.apis.still("llm", LLM_API), "an API with a fixed id is not read again")

    async def test_an_entry_that_is_not_what_the_console_gives_is_not_there_rather_than_an_error(self):
        for body in ([], "text", None, {"status": None}, {}):
            with mock.patch.object(self.web.evidence.management, "get", mock.AsyncMock(return_value=body)):
                self.assertEqual((await self.look("logs"))["state"], "pending", body)
        with mock.patch.object(self.web.evidence.management, "post", mock.AsyncMock(return_value="junk")):
            self.world.apim.record(REQUEST, MCP_API, STARTED)
            self.assertEqual((await self.look("trace", "mcp"))["state"], "pending")
            self.assertEqual((await self.look("decisions", "mcp"))["state"], "pending")


class ThePageOfALink(AppCase):
    """A link followed with no frame of the Lab UI to ask the route for it (a tab the browser opened): the route answers at once with a small page of the
    app's own look, which looks for the item the way the app does inside the frame (`resolve=1`, again while it is pending) and goes to it. No connection is
    held open for the wait, nothing is asked of the platform to answer it, and it carries no script of its own."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.at = int(self.world.now * 1000)
        self.page = await self.http.get(link("trace", at=self.at))

    async def test_the_answer_is_a_page_at_once_and_nothing_is_asked_of_the_platform_to_give_it(self):
        self.assertEqual((self.page.status_code, self.page.headers["content-type"], self.page.headers["cache-control"]), (200, "text/html; charset=utf-8", "no-store"))
        self.assertEqual(self.world.apim.log, [])
        self.assertEqual(self.world.apim.log_reads, [])

    async def test_the_page_has_no_script_of_its_own_and_loads_nothing_from_elsewhere(self):
        html = self.page.text
        for script in re.findall(r"<script\b[^>]*>.*?</script>", html, re.DOTALL):
            self.assertRegex(script, r'^<script (?:type="module" )?src="/[\w./-]+"></script>$', "a script is a file of the app")
        self.assertEqual(re.findall(r"<script\b", html).__len__(), 2, "the theme and the page's own script")
        self.assertNotRegex(html, r"\son\w+\s*=", "no handler written in the markup")
        self.assertNotIn("style=", html)
        for address in re.findall(r'(?:src|href)="([^"]+)"', html):
            self.assertTrue(address.startswith(("/", "data:image/")), address)
        policy = self.page.headers["content-security-policy"]
        self.assertIn("default-src 'self'", policy)
        self.assertNotIn("unsafe", policy)
        self.assertNotIn("script-src", policy)                                      # nothing relaxes default-src for scripts
        for path in re.findall(r'(?:src|href)="(/[^"]+)"', html):
            self.assertEqual((await self.http.get(path)).status_code, 200, path)

    async def test_the_page_is_the_one_look_of_the_app_and_says_nothing_of_the_call(self):
        html = self.page.text
        self.assertIn('<link rel="stylesheet" href="/style.css">', html)
        self.assertIn('<script src="/theme.js"></script>', html)                 # a chosen theme is the page's too
        self.assertNotIn(REQUEST, html, "the address says which call: the script reads it, the page holds nothing")
        self.assertNotIn(LLM_API, html)
        self.assertIn('role="status"', html)                                       # what it says is said to a screen reader
        self.assertEqual(html.count("Gamma"), 1, "its words are the app's (words.js): only what a page without scripts must say is written here")
        self.assertIn("needs JavaScript", html)

    async def test_the_same_page_whatever_the_state_of_the_item_and_the_platform(self):
        self.world.transport.hosts.pop("apim.test")
        down = await self.http.get(link("decisions", "mcp", at=self.at))
        self.assertEqual((down.status_code, down.text), (200, self.page.text))
        self.world.apim.record(REQUEST, LLM_API, STARTED)

    async def test_a_head_of_it_is_the_page_too_and_asks_the_platform_nothing(self):
        response = await self.http.head(link("logs", at=self.at))
        self.assertEqual((response.status_code, self.world.apim.log), (200, []))

    async def test_nothing_is_held_open_the_route_has_no_wait_of_its_own(self):
        """What it waited for is the page's to ask again for: a route that holds a request for twenty seconds, for any link, is a way to hold the app's connections."""
        for name in ("follow", "FOLLOW", "POLL", "sleep"):
            self.assertFalse(hasattr(evidence, name) or hasattr(self.web.evidence, name), name)


class OnlyWhatThePageMakes(AppCase):
    """The route looks things up with the platform's admin login: it takes only the shapes the page makes, from this page only."""

    NOW = 1_791_504_000_000

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.now = self.NOW / 1000
        self.web.evidence.clock = lambda: self.now

    async def test_a_link_that_is_not_one_the_page_makes_is_refused_and_nothing_is_asked_of_the_platform(self):
        good = f"kind=logs&api=llm&request={REQUEST}&at={self.NOW}"
        bad = ("", "kind=logs", f"kind=gamma&api=llm&request={REQUEST}&at={self.NOW}", f"kind=LOGS&api=llm&request={REQUEST}&at={self.NOW}",
               f"kind=logs&api=gamma&request={REQUEST}&at={self.NOW}", f"kind=logs&api=LLM&request={REQUEST}&at={self.NOW}",
               f"kind=logs&api=llm&at={self.NOW}", f"kind=logs&api=llm&request=short&at={self.NOW}", f"kind=logs&api=llm&request={'a' * 65}&at={self.NOW}",
               f"kind=logs&api=llm&request=ab%2Fcd%3Fx%3D1234&at={self.NOW}", f"kind=logs&api=llm&request={REQUEST}%0A&at={self.NOW}",
               f"kind=logs&api=llm&request=../../etc/passwd&at={self.NOW}", f"kind=logs&api=llm&request={REQUEST}",
               f"kind=logs&api=llm&request={REQUEST}&at=now", f"kind=logs&api=llm&request={REQUEST}&at=1.5", f"kind=logs&api=llm&request={REQUEST}&at=-1",
               f"kind=logs&api=llm&request={REQUEST}&at=0", f"kind=logs&api=llm&request={REQUEST}&at=946684799999",
               f"kind=logs&api=llm&request={REQUEST}&at={10 ** 20}", f"kind=logs&api=llm&request={REQUEST}&at={self.NOW + 61_000}",
               f"{good}&since=x", f"{good}&since={self.NOW + 1}", f"{good}&since={self.NOW - 86_400_001}", f"{good}&since=-5")
        for query in bad:
            for resolve in ("", "&resolve=1"):
                response = await self.http.get(f"/api/evidence?{query}{resolve}", follow_redirects=False)
                self.assertEqual(response.status_code, 400, query)
                self.assertIn("error", response.json())
        self.assertEqual(self.world.apim.log, [])

    async def test_the_edges_of_what_a_call_can_be_are_calls(self):
        for at, since in ((946_684_800_000, None), (self.NOW + 60_000, None), (self.NOW, self.NOW), (self.NOW, self.NOW - 86_400_000)):
            query = f"kind=logs&api=llm&request={REQUEST}&at={at}" + (f"&since={since}" if since is not None else "")
            self.assertEqual((await self.http.get(f"/api/evidence?{query}&resolve=1")).status_code, 200, query)

    async def test_the_shapes_the_page_makes_are_taken(self):
        for kind, api in (("trace", "a2a"), ("trace", "llm"), ("trace", "mcp"), ("trace", "teams"), ("logs", "mcp"), ("decisions", "mcp"), ("spend", "teams")):
            response = await self.http.get(f"/api/evidence?kind={kind}&api={api}&request={REQUEST}&at={self.NOW}&resolve=1")
            self.assertEqual(response.status_code, 200, (kind, api))

    async def test_a_page_elsewhere_cannot_make_the_app_look_things_up(self):
        url = f"/api/evidence?kind=logs&api=llm&request={REQUEST}&at={self.NOW}"
        for headers in ({"Origin": "http://evil.example"}, {"Origin": "", "Sec-Fetch-Site": "cross-site"}, {"Origin": "", "Sec-Fetch-Site": "same-site"}):
            for resolve in ("", "&resolve=1"):
                self.assertEqual((await self.http.get(url + resolve, headers=headers)).status_code, 403, headers)
        self.assertEqual((await self.http.get(url, headers={"Host": "evil.example"})).status_code, 421, "a name that points here is not this app's")
        self.assertEqual(self.world.apim.log, [], "nothing was asked of the platform for any of them")

    async def test_a_link_opened_by_a_person_needs_no_header_a_link_cannot_carry(self):
        bare = self.browser()
        del bare.headers["X-Requested-With"]
        self.addAsyncCleanup(bare.aclose)
        url = f"/api/evidence?kind=logs&api=llm&request={REQUEST}&at={self.NOW}"
        self.assertEqual((await bare.get(url)).status_code, 200)
        self.assertEqual((await bare.get(url, headers={"Origin": "", "Sec-Fetch-Site": "cross-site"})).status_code, 403)

    async def test_the_route_only_answers_a_get(self):
        for method in ("post", "put", "delete"):
            self.assertEqual((await getattr(self.http, method)("/api/evidence")).status_code, 405, method)


class Resolving(AppCase):
    """The items of the call a result names are found: the ids that were given in the call are the ones the route looks for."""

    async def test_every_evidence_link_of_a_hop_finds_the_exact_item_of_the_call_it_names(self):
        self.web.evidence.clock = lambda: self.world.now
        await self.sign_in("bob")
        out = (await self.http.post("/api/commands/read-other-accounts/run", json={})).json()
        denied = next(r for r in out["rows"] if r["outcome"] == "denied")
        self.world.apim.record(denied["request_id"], MCP_API, STARTED)
        self.world.apim.decide(denied["request_id"], EVENT)
        self.world.apim.traces = [trace(TRACE, MCP_API, STARTED, denied["request_id"], "tools/call")]
        found = {}
        for item in denied["evidence"]:
            response = await self.http.get(item["url"] + "&resolve=1")
            self.assertEqual(response.json()["state"], "found", item["kind"])
            found[item["kind"]] = response.json()["url"]
        self.assertEqual(found, {"trace": f"{GAMMA}/aim/observe/tracing/{MCP_API}/{TRACE}",
                                 "logs": f"{GAMMA}/aim/observe/logs/{denied['request_id']}?apiId={MCP_API}",
                                 "decisions": f"{GAMMA}/authz/observe/logs/{EVENT}?apiId={MCP_API}"})

    async def test_each_hop_of_an_answer_is_found_in_the_api_that_served_it_by_the_request_of_its_own_call(self):
        """The call to Ace, the list of tools, the model and the tool are four requests in three APIs: the buttons of each open that request in that API."""
        self.web.evidence.clock = lambda: self.world.now
        await self.sign_in("alice")
        out = (await self.http.post("/api/chat", json={"message": "Show my accounts and balances"})).json()
        apis = {"a2a": A2A_API, "mcp": MCP_API, "llm": LLM_API}
        for row in out["rows"]:
            if row["api"]:
                self.world.apim.record(row["request_id"], apis[row["api"]], STARTED)
        for row in out["rows"]:
            for item in row["evidence"]:
                if item["kind"] != "logs":
                    continue
                found = (await self.http.get(item["url"] + "&resolve=1")).json()
                self.assertEqual(found, {"state": "found", "url": f"{GAMMA}/aim/observe/logs/{row['request_id']}?apiId={apis[row['api']]}"}, row["title"])

    async def test_the_answer_of_the_developers_key_and_of_a_team_are_found_by_the_request_the_gateway_gave_them(self):
        self.web.evidence.clock = lambda: self.world.now
        dev = (await self.http.post("/api/dev/llm", json={"message": "Explain a mortgage"})).json()
        team = (await self.http.post("/api/teams/chat", json={"team": "team-care", "kind": "short"})).json()
        self.world.apim.record(dev["request_id"], LLM_API, STARTED)
        self.world.apim.record(team["request_id"], TEAMS_API, STARTED, applicationId="82f877b4-4005-416c-b877-b44005c16ce7")
        for answer, api_id in ((dev, LLM_API), (team, TEAMS_API)):
            urls = {e["kind"]: e["url"] for e in answer["rows"][0]["evidence"]}
            logs = (await self.http.get(urls["logs"] + "&resolve=1")).json()
            self.assertEqual(logs["url"], f"{GAMMA}/aim/observe/logs/{answer['request_id']}?apiId={api_id}")
        spend = (await self.http.get(urls["spend"] + "&resolve=1")).json()
        self.assertEqual(decoded(spend["url"])["c"][1]["value"], ["82f877b4-4005-416c-b877-b44005c16ce7"])

    async def test_a_payment_with_the_users_own_token_is_found_by_the_request_of_its_tool_call(self):
        self.web.evidence.clock = lambda: self.world.now
        await self.sign_in("alice")
        paid = (await self.http.post("/api/send-money", json={"from_account": "ACC-1001", "to_account": "ACC-2001", "amount": 12000})).json()
        self.world.apim.record(paid["request_id"], MCP_API, STARTED)
        self.world.apim.decide(paid["request_id"], EVENT)
        for item in paid["evidence"]:
            if item["kind"] != "trace":
                self.assertEqual((await self.http.get(item["url"] + "&resolve=1")).json()["state"], "found", item["kind"])


class TheRoute(AppCase):
    def test_a_link_is_made_only_for_a_call_that_has_a_request(self):
        self.assertIsNone(route("logs", "llm", None, 1))
        self.assertIsNone(route("logs", "llm", "", 1))
        self.assertEqual(route("logs", "llm", REQUEST, 1_791_504_000_000), f"/api/evidence?kind=logs&api=llm&request={REQUEST}&at=1791504000000")
        self.assertTrue(route("spend", "teams", REQUEST, 5, since=3).endswith("&at=5&since=3"))

    def test_what_the_route_makes_the_route_takes(self):
        now = 1_791_504_000.0
        for kind in evidence.KINDS:
            for api in evidence.APIS:
                url = route(kind, api, REQUEST, 1_791_504_000_000, since=1_791_503_990_000)
                query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
                self.assertEqual(parse(query, now), Item(kind, api, REQUEST, 1_791_504_000_000, 1_791_503_990_000))

    def test_a_request_is_matched_whole(self):
        for fine in ("req-llm-1", "5f0e1a52-7c0e-4b3d-9d3a-3f6c2b1a9e01", "a" * 64, "A_b-c-d-e"):
            self.assertEqual(clean(fine), fine)
        for junk in ("short", "a" * 65, "req-llm-1\n", "req llm 1", "req/llm/1", "ééééééééé", "", None, 12345678, b"req-llm-1"):
            self.assertIsNone(clean(junk), junk)
        with self.assertRaises(BadItem):
            parse({"kind": "logs", "api": "llm", "request": "x\n" * 8, "at": "1791504000000"}, 1_791_504_000.0)
