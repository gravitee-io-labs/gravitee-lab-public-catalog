"""The chat: the user's question goes to Ace over A2A with the user's own token, through the gateway or, with the
gateway off, straight to the same Ace without it."""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, NoReturn

import httpx
from a2a.client import ClientCallContext, ClientConfig, create_client
from a2a.helpers import get_data_parts, get_message_text, new_message, new_text_part
from a2a.types import AgentCard, AgentInterface, Role, SendMessageRequest

import hops
import mcp_rpc
from am import AccessManagement
from sessions import Session
from settings import Settings
from upstream import Clients, UpstreamError, elapsed_ms, message_of, recording

log = logging.getLogger("bank-web.chat")

NOT_ANSWERING = "Ace is not answering. Try again in a minute."
REFUSED_WITHOUT_TOKEN = "The gateway refused the question: it asks for a token, and none was sent."
MAX_MESSAGE = 2000


@dataclass
class Answer:
    text: str
    context_id: str | None
    trace: list = field(default_factory=list)
    delegated_claims: dict[str, Any] | None = None
    tools: list[str] | None = None            # the tools Ace listed for this person: what it may use


class Ace:
    """The A2A client of one Ace address. The card is built here, not fetched: behind an OAuth2 plan the card
    itself needs the token, and the address of its interface is the one asked for anyway."""

    def __init__(self, http: httpx.AsyncClient):
        self.http = http
        self._clients: dict[str, Any] = {}

    async def _client(self, url: str):
        if url not in self._clients:
            card = AgentCard(name="Ace", supported_interfaces=[
                AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")])
            self._clients[url] = await create_client(
                card, client_config=ClientConfig(httpx_client=self.http, streaming=False))
        return self._clients[url]

    async def ask(self, url: str, token: str | None, text: str, context_id: str | None, seen: dict) -> Answer:
        """The question to Ace, with the person's token; `token` None sends none, which the gateway's OAuth2 plan refuses."""
        client = await self._client(url)
        message = new_message([new_text_part(text)], role=Role.ROLE_USER, context_id=context_id)
        request = SendMessageRequest(message=message)
        call = ClientCallContext(service_parameters={"Authorization": f"Bearer {token}"} if token else {}, timeout=120)
        answer = Answer("", context_id)
        try:
            replies = [chunk.message async for chunk in client.send_message(request, context=call)
                       if chunk.WhichOneof("payload") == "message"]
        except Exception as e:    # noqa: BLE001 - an answer that is no A2A answer raises more than the SDK's own errors
            log.warning("the A2A call failed: %s", type(e).__name__)
            raise self._failure(seen, signed=bool(token)) from e
        for message in replies:
            self._read(message, answer)
        if not answer.text:
            raise UpstreamError(NOT_ANSWERING)
        return answer

    @staticmethod
    def _read(message, answer: Answer) -> None:
        answer.text = get_message_text(message)
        answer.context_id = message.context_id or answer.context_id
        for data in get_data_parts(message.parts):
            answer.trace += data.get("trace", [])
            answer.delegated_claims = data.get("delegated_claims") or answer.delegated_claims
            listed = data.get("tools")
            if isinstance(listed, list) and all(isinstance(name, str) for name in listed):
                answer.tools = listed

    @staticmethod
    def _failure(seen: dict, signed: bool = True) -> UpstreamError:
        """The SDK keeps only a text for an HTTP error: the status comes from what `recording` saw."""
        if seen.get("status") in (401, 403):
            if not signed:
                return UpstreamError(REFUSED_WITHOUT_TOKEN, 401)
            return UpstreamError(
                "The gateway did not accept your sign-in. Sign in again; if it repeats, re-seed the playground.", 401)
        return UpstreamError(NOT_ANSWERING, 504 if seen.get("status") == 504 else 502)


class Chat:
    def __init__(self, clients: Clients, settings: Settings, am: AccessManagement):
        self.clients, self.settings, self.am = clients, settings, am
        self.ace = Ace(clients.a2a)
        self._catalog: list[str] | None = None

    async def turn(self, session: Session, message: str, gateway_on: bool) -> dict:
        """One question to Ace, and the hops it went through: the call to Ace first, then Ace's own (its token, its tools, the model, each tool)."""
        mode = "on" if gateway_on else "off"
        person = session.persona
        token = await self.am.valid_token(session)
        started = time.monotonic()
        with recording() as seen:
            try:
                answer = await self.ace.ask(self.settings.ace_url if gateway_on else self.settings.ace_direct_url,
                                            token, message, session.contexts.get(mode), seen)
            except UpstreamError as e:
                if seen.get("status", 0) >= 400:      # the gateway answered, with a refusal or a failure: that call is a hop, with its own evidence
                    e.rows = [self._ace_row(person, gateway_on, seen, elapsed_ms(started), message_of(_json(seen.get("body"))))]
                raise
        ms = elapsed_ms(started)
        session.contexts[mode] = answer.context_id
        session.delegated_claims = answer.delegated_claims
        calls = hops.rows(answer.trace, person=person, gateway=gateway_on, claims=answer.delegated_claims, offered=answer.tools,
                          catalog=await self._every_tool())
        rows = [self._ace_row(person, gateway_on, seen, ms, calls=len(calls)), *calls]
        log.info("chat %s gateway=%s %s %d ms", person.id, mode, [f"{r['title']}:{r['word']}" for r in rows], ms)
        return {"answer": answer.text, "gateway": mode, "protected": gateway_on, "ms": ms, "rows": rows, "delegated_claims": answer.delegated_claims}

    async def without_token(self, message: str) -> NoReturn:
        """The question sent with no token at all, to the gateway: the OAuth2 plan of the A2A proxy refuses it, and this raises that refusal with its hop (the call
        to Ace, its status, its request id: its Logs are the gateway's own record of it). It never returns an answer: one that came would be a gateway that asks
        for no token."""
        started = time.monotonic()
        with recording() as seen:
            try:
                await self.ace.ask(self.settings.ace_url, None, message, None, seen)
            except UpstreamError as e:
                if seen.get("status", 0) >= 400:
                    e.rows = [self._ace_row(None, True, seen, elapsed_ms(started), hops.NO_TOKEN, 0)]
                raise
        raise UpstreamError("The gateway answered a question that carried no token: it asks for none.", 502)

    @staticmethod
    def _ace_row(person, gateway_on: bool, seen: dict, ms: int, detail: str = "", calls: int = 0) -> dict:
        return hops.asked_ace(person, gateway=gateway_on, status=seen.get("status"), ms=ms, detail=detail, calls=calls,
                              transaction_id=seen.get("transaction_id") if gateway_on else None, request_id=seen.get("request_id") if gateway_on else None)

    async def _every_tool(self) -> list[str] | None:
        """Every tool the bank's server has (what Ace may use is counted out of them), read once. None where the bank does not answer: a count is then not said."""
        if self._catalog is None:
            try:
                self._catalog = await mcp_rpc.list_tools(self.clients.internal, self.settings.mcp_direct_url)
            except UpstreamError:
                return None
        return self._catalog


def _json(raw: str | None) -> Any:
    try:
        return json.loads(raw or "")
    except ValueError:
        return raw
