"""The evidence of one call, in Gamma: the exact item, looked for when its button is pressed.

An answer carries, for each of Trace, Logs, Decisions and Spend, a route of this app (`GET /api/evidence`) that names the call by what the gateway
said of it: the id of the request and the API that served it. Gamma opens one item by an address that needs its own ids, which are not the
request's, and the item is there only some seconds after the call: the route finds the ids and waits for the item, so the person lands on the
log entry, the trace or the decision of that call and not on a list to read.

    logs       the entry itself: `observe/logs/<request id>?apiId=`, which needs only the two ids the app has. It is complete (its status is
               there) some 5 to 10 s after the call; before that Gamma answers "not found" and does not look again.
    trace      one gateway request is one trace, whose id is neither the request's nor the transaction's: the log gives the moment the request
               started, the traces that started then are read, and the one whose spans name the request (`gravitee.request.id`) is the call's, once its
               root span is written (the spans are written as they end, the root last: a trace opened sooner shows part of the call, and is not read again).
    decisions  the record of the policy engine for that request, found by a search on the request id (the page of a decision takes the id of its
               event); a few seconds after the call.
    spend      no page of Gamma has the Spend of a call: the dashboard of the workspace is filtered on the person and on the time of the run, which is
               what it cost. It is complete when the log of the last call is (the same moment).

Nothing the platform says is passed on: the answer is a state and an address built from ids that were checked. An item that is not there yet is
`pending` (for a while after the call), then `missing`, with the list it belongs to as the way in that is left. The route looks once and says which:
whoever follows a link (the page of the app, or the small page of a tab the browser opened) asks again by itself while it is `pending`, so that no
connection is held open for the wait.
"""
import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode

from apis import Apis
from bounds import AT_RANGE, FUTURE, SPAN
from links import Links
from management import Management
from upstream import ID, UpstreamError

log = logging.getLogger("bank-web.evidence")

KINDS = ("trace", "logs", "decisions", "spend")
APIS = ("a2a", "llm", "mcp", "teams")
ROUTE = "/api/evidence"
TRACE_ID = re.compile(r"[0-9a-f]{32}")
ATTRIBUTE = "gravitee.request.id"                # on the spans of a trace: the request it belongs to

FOUND, PENDING, MISSING, DOWN = "found", "pending", "missing", "down"
GRACE = {"logs": 25, "trace": 25, "decisions": 15, "spend": 25}       # seconds after a call during which what is not there yet is expected
PASS = 8                         # seconds one look may take over the platform, whatever it does (it answers in milliseconds)
START = 2_000                    # ms between the moment a log says a request started and the trace's start: a slow call starts its trace later
CANDIDATES = 5                   # traces read at most to tell which one is the request's
BEFORE, AFTER = 90_000, 60_000   # the window of a list, around a call: ms before and after its time
DECISION_BEFORE = 10 * 60_000    # a decision is searched from this far before the link was made
RUN_BEFORE = 2_000               # a spend's window starts this long before the first call of the run (the clocks of the gateway and of the page differ by a little)


class BadItem(ValueError):
    """The route was asked for something the page never asks."""


@dataclass(frozen=True)
class Item:
    kind: str                    # trace, logs, decisions or spend
    api: str                     # the API that served the request: a2a, llm, mcp or teams (decisions are the MCP proxy's, a spend the workspace's)
    request: str                 # the gateway's id of the request (of the last call, for a spend)
    at: int                      # when the link was made, epoch ms: a little after the call
    since: int | None = None     # a spend: when the first call of the run started (the call's own start, whatever it lasted)

    @property
    def window(self) -> tuple[int, int]:
        return self.at - BEFORE, self.at + AFTER


def route(kind: str, api: str, request: str | None, at: int, since: int | None = None) -> str | None:
    """The address of the evidence of a call, a route of this app: followed, it finds the item in Gamma and goes there. None where the call has no
    request id (a call that did not go through the gateway has no evidence). A run does not begin after the link that is made of it."""
    if not request:
        return None
    query = {"kind": kind, "api": api, "request": request, "at": at, **({"since": min(since, at)} if since is not None else {})}
    return f"{ROUTE}?{urlencode(query)}"


def _whole(query, key: str, required: bool = True) -> int | None:
    value = query.get(key)
    if value is None and not required:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise BadItem(f"{key} is a number of milliseconds") from e


def parse(query, now: float) -> Item:
    """The item a route asks for, or `BadItem`: only the shapes `route` makes."""
    kind, api, request = query.get("kind", ""), query.get("api", ""), query.get("request", "")
    if kind not in KINDS or api not in APIS or not ID.fullmatch(request):
        raise BadItem("kind, api or request is not one the page makes")
    at, since = _whole(query, "at"), _whole(query, "since", required=False)
    if not AT_RANGE[0] <= at <= min(AT_RANGE[1], now * 1000 + FUTURE):
        raise BadItem("at is the time of the call in milliseconds")
    if since is not None and not at - SPAN <= since <= at:
        raise BadItem("since is when the run started, in milliseconds, a day before at at most")
    return Item(kind, api, request, at, since)


def stamp(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Found:
    state: str                   # found, pending, missing or down
    url: str | None = None       # the item (found), else the list it belongs to (missing, down)


class Evidence:
    def __init__(self, management: Management, apis: Apis, workspace, links: Links, clock=time.time):
        """`workspace` is an async function: the id of the AI workspace, None where the platform does not say."""
        self.management, self.apis, self.workspace, self.links = management, apis, workspace, links
        self.clock = clock

    # -- looking --------------------------------------------------------------------------------------------------------------
    async def look(self, item: Item) -> Found:
        """One look at the platform: the item if it is there, `pending` if it is expected, else `missing` (with the list instead) or `down`."""
        try:
            async with asyncio.timeout(PASS):
                url = await self._exact(item)
        except (UpstreamError, TimeoutError) as e:
            log.info("the %s of a call could not be looked for: %s", item.kind, getattr(e, "message", "the platform took too long"))
            return Found(DOWN, await self._list(item))
        if url:
            return Found(FOUND, url)
        if 0 <= self.clock() - item.at / 1000 < GRACE[item.kind]:
            return Found(PENDING)
        return Found(MISSING, await self._list(item))

    # -- the exact item ---------------------------------------------------------------------------------------------------------
    async def _exact(self, item: Item) -> str | None:
        return await {"logs": self._log, "trace": self._trace, "decisions": self._decision, "spend": self._spend}[item.kind](item)

    async def _entry(self, api_id: str, request: str) -> dict | None:
        """The log entry of a request once it is complete: Gamma writes it twice (the ids first, a second later the rest) and a page opened
        in between shows nothing."""
        try:
            entry = await self.management.get(f"{self.management.observability}/logs/{request}", apiId=api_id)
        except UpstreamError as e:
            if e.upstream == 404:
                return None
            raise
        return entry if isinstance(entry, dict) and entry.get("status") is not None else None

    async def _api(self, key: str) -> str:
        """The id of an API of the story. One the platform does not name (it is not answering, or the API is being made again) is no id: it is looked
        for again at once and not after the wait that spares the platform, and then the platform is down for what it is asked."""
        api_id = await self.apis.id(key)
        if not api_id:
            self.apis.forget(key)
            api_id = await self.apis.id(key)
        if not api_id:
            raise UpstreamError(f"The platform does not name the API for {key}", 503)
        return api_id

    async def _entry_of(self, key: str, request: str) -> tuple[str, dict | None]:
        """The API behind `key` and the log entry of a request in it. An entry that is not there may be one that is not written yet, or one of an API
        that was made again since its id was read (a re-seed does it for the MCP proxy and the workspace): where the platform answers 404 for the API
        that was asked, its id is read again by its name and the entry is looked for there."""
        api_id = await self._api(key)
        entry = await self._entry(api_id, request)
        if entry is None and not await self.apis.still(key, api_id):
            api_id = await self._api(key)
            entry = await self._entry(api_id, request)
        return api_id, entry

    async def _log(self, item: Item) -> str | None:
        api_id, entry = await self._entry_of(item.api, item.request)
        return self.links.log(api_id, item.request) if entry else None

    async def _trace(self, item: Item) -> str | None:
        api_id, entry = await self._entry_of(item.api, item.request)
        started = entry.get("timestampEpochMs") if entry else None
        if not isinstance(started, int) or isinstance(started, bool):
            return None
        listed = await self.management.post(f"{self.management.observability}/traces/search",
                                            {"apiId": api_id, "timeRange": {"from": stamp(started - 2000), "to": stamp(started + 3000)}}, page=1, perPage=100)
        near = sorted((t for t in (listed.get("data", []) if isinstance(listed, dict) else [])
                       if isinstance(t, dict) and isinstance(t.get("startTimeEpochMs"), int) and TRACE_ID.fullmatch(str(t.get("traceId", "")))
                       and abs(t["startTimeEpochMs"] - started) <= START), key=lambda t: abs(t["startTimeEpochMs"] - started))[:CANDIDATES]
        details = await asyncio.gather(*(self.management.get(f"{self.management.observability}/traces/{t['traceId']}", apiId=api_id) for t in near),
                                       return_exceptions=True)
        for detail in details:
            if isinstance(detail, dict) and TRACE_ID.fullmatch(str(detail.get("traceId", ""))) and self._whole(detail.get("spans"), item.request):
                return self.links.trace(api_id, detail["traceId"])
        return None

    @staticmethod
    def _whole(spans: object, request: str) -> bool:
        """Whether the spans are the whole trace of the request: they name it (`gravitee.request.id`) and the root span, which ends last, is among them. The gateway
        writes the spans as they end, and a trace opened before its root is there shows some of the spans only, which Gamma does not read again."""
        spans = [span for span in spans if isinstance(span, dict)] if isinstance(spans, list) else []
        return any((span.get("attributes") or {}).get(ATTRIBUTE) == request for span in spans) and any(not span.get("parentSpanId") for span in spans)

    async def _decision(self, item: Item) -> str | None:
        found = await self.management.post(
            f"{self.management.observability}/logs/search",
            {"timeRange": {"from": stamp(item.at - DECISION_BEFORE), "to": stamp(int(self.clock() * 1000) + 60_000)},
             "filters": [{"name": "RECORD_TYPE", "operator": "EQ", "value": "AUTHZ_DECISION"},
                         {"name": "REQUEST_ID", "operator": "EQ", "value": item.request}]}, page=1, perPage=20)
        for record in found.get("data", []) if isinstance(found, dict) else []:
            if not isinstance(record, dict):
                continue
            event = (record.get("authz") or {}).get("eventId")
            if record.get("requestId") == item.request and ID.fullmatch(str(event)) and ID.fullmatch(str(record.get("apiId"))):
                return self.links.decision(record["apiId"], event)
        return None

    async def _spend(self, item: Item) -> str | None:
        _, entry = await self._entry_of("teams", item.request)
        workspace = await self.workspace() if entry else None
        if not workspace:
            return None
        application = entry.get("applicationId")
        return self.links.spend_dashboard(workspace, application if ID.fullmatch(str(application)) else None, self._run(item, entry))

    @staticmethod
    def _run(item: Item, entry: dict) -> tuple[int, int]:
        """The window of a spend: it holds the whole of the call or of the run, whatever it lasted. It opens a little before the first call began
        (the link carries when it did; the log says when the call began, and the earlier of the two is taken) and closes a little after the link was made."""
        began = entry.get("timestampEpochMs")
        starts = [item.since if item.since is not None else item.at, *([began] if isinstance(began, int) and not isinstance(began, bool) else [])]
        return max(min(starts), item.at - SPAN) - RUN_BEFORE, item.at + AFTER // 6

    # -- where to go when the item is not there ---------------------------------------------------------------------------------
    async def _list(self, item: Item) -> str:
        """The list the item belongs to, around the call, or the page of its kind: always somewhere to land, and never a guess at the item."""
        try:
            if item.kind == "logs":
                return self.links.logs_list(item.request, item.window)
            if item.kind == "decisions":
                return self.links.decisions_list(item.request, item.window)
            if item.kind == "spend":
                return self.links.spend(await self.workspace()) or self.links.workspaces()
            return self.links.trace(await self.apis.id(item.api), window=item.window) or self.links.pages()["tracing"]
        except UpstreamError:
            return {"trace": self.links.pages()["tracing"], "spend": self.links.workspaces()}.get(item.kind) or self.links.pages()[item.kind]
