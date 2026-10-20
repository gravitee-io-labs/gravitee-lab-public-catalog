"""Event Streams Management with Kafka demo app: a producer, a consumer and the broker's own view of the topic, on the Python standard library.

    python server.py          # configured by environment variables, see README.md

The producer and the consumer reach the orders stream the way a customer would: over HTTP, SSE and a webhook (the API
Orders Events), or as a native Kafka client with a certificate (the API Orders Kafka). The middle column reads the broker
itself, bypassing the gateway, so that what the policies do to a record is there to see. Nothing is kept on disk.
"""
import http.client
import json
import logging
import queue
import re
import signal
import sys
import threading
import time
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import blobs
import kafkaio
import orders
import security
from hub import Hub
from shown import shorten
from settings import Settings, SettingsError
from settings import load as load_settings
from switches import SWITCHES, Management, Unavailable

log = logging.getLogger("streams-app")

STATIC = Path(__file__).with_name("static")
ASSETS = {"/": ("index.html", "text/html; charset=utf-8"), "/static/page.css": ("page.css", "text/css; charset=utf-8"),
          "/static/page.js": ("page.js", "text/javascript; charset=utf-8"), "/static/mark.svg": ("mark.svg", "image/svg+xml"),
          "/static/logo-light.svg": ("logo-light.svg", "image/svg+xml"), "/static/logo-dark.svg": ("logo-dark.svg", "image/svg+xml")}
MAX_BODY = 2 * 1024 * 1024
HOOK_PATH = "/hooks/orders"
KEPT_HEADERS = re.compile(r"^x-(?!gravitee-)", re.IGNORECASE)         # the custom headers of a delivery; the gateway's own are noise
CHANNELS = ("kafka", "sse", "get", "webhook")


class Refused(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


@dataclass
class App:
    settings: Settings
    assets: dict[str, tuple[bytes, str]]
    hub: Hub
    management: Management
    status_cache: dict = field(default_factory=dict)
    status_lock: threading.Lock = field(default_factory=threading.Lock)


def load_assets(folder: Path = STATIC) -> dict[str, tuple[bytes, str]]:
    return {path: ((folder / name).read_bytes(), kind) for path, (name, kind) in ASSETS.items()}


def dumps(value) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


# --- What the app asks of the gateway over HTTP ---------------------------------------------------------------------------

def gateway_connection(settings: Settings, timeout: float | None) -> http.client.HTTPConnection:
    parts = urllib.parse.urlsplit(settings.gateway_url)
    return http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)


def http_post(settings: Settings, order: dict) -> dict:
    started = time.monotonic()
    try:
        connection = gateway_connection(settings, 10)
        connection.request("POST", "/orders/", body=dumps(order), headers={"X-Gravitee-Api-Key": settings.orders_key, "Content-Type": "application/json"})
        answer = connection.getresponse()
        answer.read()
        took = round((time.monotonic() - started) * 1000)
        if answer.status in (200, 202):
            return {"ok": True, "status": answer.status, "ms": took}
        return {"ok": False, "status": answer.status, "ms": took, "error": f"The gateway answered {answer.status} {HTTPStatus(answer.status).phrase}"}
    except OSError as error:
        return {"ok": False, "error": f"Cannot reach the gateway: {error}"}


def message_event(value: str, channel: str, extra: dict | None = None) -> dict:
    return {"type": "message", "channel": channel, "value": shorten(value), "size": len(value.encode()), "received": time.time(), **(extra or {})}


def threaded(work, stop: threading.Event) -> Iterator[dict | None]:
    """Runs `work(put)` in a thread and yields what it puts, or None every second. `stop` ends the thread when the reader goes."""
    inbox: queue.Queue = queue.Queue()
    worker = threading.Thread(target=work, args=(inbox.put,), daemon=True)
    worker.start()
    try:
        while worker.is_alive() or not inbox.empty():
            try:
                yield inbox.get(timeout=1)
            except queue.Empty:
                yield None
    finally:
        stop.set()


WHO = ("dashboard", "france", "germany")        # the HTTP readers: the dashboard (every order) and the two partners (their country)
APIS = {"orders": "/orders/", "avro": "/orders-avro/"}


def relay_sse(settings: Settings, who: str = "dashboard", api: str = "orders") -> Iterator[dict | None]:
    """The SSE stream of an HTTP API, as a reader of it would open it."""
    stop = threading.Event()
    connections: list[http.client.HTTPConnection] = []

    def work(put) -> None:
        try:
            connection = gateway_connection(settings, None)
            connections.append(connection)
            connection.request("GET", APIS[api], headers={"X-Gravitee-Api-Key": settings.partner_keys[who], "Accept": "text/event-stream"})
            answer = connection.getresponse()
            if answer.status != 200:
                put({"type": "error", "message": f"The gateway answered {answer.status} {HTTPStatus(answer.status).phrase}"})
                return
            put({"type": "status", "ready": True, "message": f"Connected: Accept text/event-stream on {APIS[api]}"})
            while not stop.is_set():
                line = answer.readline()
                if not line:
                    put({"type": "error", "message": "The gateway closed the stream"})
                    return
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if text.startswith("data:"):
                    put(message_event(text[5:].lstrip(), "sse"))
        except OSError as error:
            if not stop.is_set():
                put({"type": "error", "message": f"SSE stream ended: {error}"})

    try:
        yield from threaded(work, stop)
    finally:
        for connection in connections:
            connection.close()


def poll_get(settings: Settings, who: str = "dashboard", api: str = "orders") -> Iterator[dict | None]:
    """Plain HTTP GET calls, one after the other: each returns what arrived since the last one."""
    stop = threading.Event()

    def work(put) -> None:
        put({"type": "status", "ready": True, "message": f"Polling GET {APIS[api]}: each call waits up to 5 s for new orders"})
        while not stop.is_set():
            try:
                connection = gateway_connection(settings, 20)
                connection.request("GET", APIS[api], headers={"X-Gravitee-Api-Key": settings.partner_keys[who], "Accept": "application/json"})
                answer = connection.getresponse()
                body = answer.read()
                connection.close()
                if answer.status != 200:
                    put({"type": "error", "message": f"The gateway answered {answer.status} {HTTPStatus(answer.status).phrase}"})
                    time.sleep(2)
                    continue
                for item in json.loads(body or b"{}").get("items", []):
                    put(message_event(item.get("content", ""), "get"))
            except (OSError, ValueError) as error:
                put({"type": "error", "message": f"GET failed: {error}"})
                time.sleep(2)

    yield from threaded(work, stop)


def webhook_events(app: App) -> Iterator[dict | None]:
    """What the gateway pushed to the callback URL, the last ones first and then as they come."""
    listener = app.hub.subscribe()
    yield {"type": "status", "ready": True, "message": f"Waiting for the gateway to call {HOOK_PATH}"}
    try:
        for event in app.hub.recent()[-20:]:
            yield event
        while True:
            try:
                yield listener.get(timeout=1)
            except queue.Empty:
                yield None
    finally:
        app.hub.unsubscribe(listener)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address: tuple[str, int], app: App) -> None:
        super().__init__(address, Handler)
        self.app = app


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 120
    server: Server

    def version_string(self) -> str:
        return "streams-app"

    def log_message(self, format: str, *args) -> None:
        """The access log is off: nothing of an order goes to a log."""

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self.close_connection = True
        self.respond(code, dumps({"error": message or HTTPStatus(code).phrase}), "application/json")

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except ConnectionError:
            self.close_connection = True

    def do_GET(self) -> None:
        self.dispatch("GET")

    def do_POST(self) -> None:
        self.dispatch("POST")

    def do_HEAD(self) -> None:
        self.dispatch("GET")           # the same answer without its body: what a look at the page's headers asks for

    # Answers

    def respond(self, status: int, body: bytes, kind: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in {**security.hardened(), **(headers or {})}.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, value, status: int = 200) -> None:
        self.respond(status, dumps(value), "application/json")

    def body(self) -> bytes:
        """The request's body, read once: a route that does not look at it must still leave the connection ready for the next request."""
        if self._body is None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise Refused(400, "Bad Content-Length") from None
            if length > MAX_BODY:
                raise Refused(413, "Body too large")
            self._body = self.rfile.read(length) if length else b""
        return self._body

    def payload(self) -> dict:
        try:
            value = json.loads(self.body() or b"{}")
        except ValueError:
            raise Refused(400, "The body is not JSON") from None
        if not isinstance(value, dict):
            raise Refused(400, "The body is not a JSON object")
        return value

    def stream(self, events: Iterator[dict | None]) -> None:
        """Server-sent events to the page, until it goes."""
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        for name, value in security.hardened().items():
            self.send_header(name, value)
        self.end_headers()
        try:
            for event in events:
                self.wfile.write(b": beat\n\n" if event is None else b"data: " + dumps(event) + b"\n\n")
                self.wfile.flush()
        except OSError:
            pass
        finally:
            events.close()

    # Routing

    def dispatch(self, method: str) -> None:
        self._body = None
        url = urllib.parse.urlsplit(self.path)
        path, query = url.path, urllib.parse.parse_qs(url.query)
        app = self.server.app
        try:
            if path != "/health":
                self.guard(method, path)
            if method == "GET":
                self.get(app, path, query)
            else:
                self.body()
                self.post(app, path)
        except Refused as refusal:
            self.json({"error": refusal.message}, refusal.status)
        except Unavailable as problem:
            self.json({"error": str(problem)}, 502)
        except Exception:
            log.exception("Unexpected error on %s %s", method, path)
            self.json({"error": "Unexpected error"}, 500)

    def guard(self, method: str, path: str) -> None:
        app = self.server.app
        host = self.headers.get("Host", "")
        if not security.host_allowed(host, app.settings.hosts):
            raise Refused(421, "Unknown host")
        if method == "POST":
            webhook = path == HOOK_PATH
            if not security.is_json(self.headers.get("Content-Type"), may_be_missing=webhook):
                raise Refused(415, "Send JSON")
            if not security.from_this_page(self.headers.get("Origin"), self.headers.get("Sec-Fetch-Site"), host):
                raise Refused(403, "This page only")

    @staticmethod
    def one(query: dict, name: str, allowed: tuple[str, ...], default: str) -> str:
        value = (query.get(name) or [default])[0]
        if value not in allowed:
            raise Refused(400, f"{name} is one of {', '.join(allowed)}")
        return value

    def get(self, app: App, path: str, query: dict) -> None:
        settings = app.settings
        if path == "/health":
            return self.json({"status": "ok"})
        if path in app.assets:
            body, kind = app.assets[path]
            return self.respond(200, body, kind)
        if path == "/api/config":
            return self.json({"hook": f"http://streams-app:8000{HOOK_PATH}", "kafka": {"orders": settings.kafka_orders, "payments": settings.kafka_payments, "partners": settings.partners_bootstrap},
                              "broker": settings.broker, "topics": {"orders": settings.orders_topic, "payments": settings.payments_topic, "avro": settings.avro_topic},
                              "switches": SWITCHES, "gateway": settings.gateway_url})
        if path == "/api/status":
            return self.json(self.status(app))
        if path == "/api/switches":
            return self.json({"states": app.management.states()})
        if path == "/api/links":
            return self.json(app.management.links(settings))
        if path == "/api/blobs":
            return self.json({"blobs": blobs.listing(settings)})
        if path == "/api/blob":
            name = (query.get("name") or [""])[0]
            if not re.fullmatch(r"[\w.-]{1,120}", name):
                raise Refused(400, "Bad blob name")
            return self.json(blobs.preview(settings, name))
        if path == "/api/probe":
            host = (query.get("host") or ["orders"])[0]
            if not re.fullmatch(r"[a-z0-9-]{1,30}", host):
                raise Refused(400, "Host is a name of letters, digits and dashes")
            identity = self.one(query, "identity", kafkaio.IDENTITIES, "fulfillment")
            return self.json(kafkaio.probe(settings, host, identity))
        if path == "/api/stream/broker":
            return self.stream(kafkaio.tail_broker(settings))
        if path.startswith("/api/stream/"):
            channel = path.rsplit("/", 1)[1]
            if channel == "kafka":
                host = self.one(query, "host", kafkaio.HOSTS, "orders")
                identity = self.one(query, "identity", kafkaio.IDENTITIES, "fulfillment")
                return self.stream(kafkaio.tail_gateway(settings, host, identity, (query.get("from") or [""])[0] == "beginning"))
            if channel in ("sse", "get"):
                who, api = self.one(query, "who", WHO, "dashboard"), self.one(query, "api", tuple(APIS), "orders")
                if api == "avro" and who != "dashboard":
                    raise Refused(400, "The partners have no subscription to the Avro API")
                return self.stream((relay_sse if channel == "sse" else poll_get)(settings, who, api))
            if channel == "webhook":
                return self.stream(webhook_events(app))
        raise Refused(404, "Not found")

    def post(self, app: App, path: str) -> None:
        settings = app.settings
        if path == HOOK_PATH:
            raw = self.body()
            kept = {k: v[:200] for k, v in self.headers.items() if KEPT_HEADERS.match(k)}
            app.hub.publish(message_event(raw.decode("utf-8", errors="replace"), "webhook", {"headers": [[k, v] for k, v in kept.items()]}))
            return self.json({"received": True})
        if path == "/api/produce":
            body = self.payload()
            channel = body.get("channel")
            if channel not in ("kafka", "http", "avro"):
                raise Refused(400, "channel is kafka, http or avro")
            order = orders.make(customer=body.get("customer"), country=body.get("country"),
                                amount=body.get("amount") if isinstance(body.get("amount"), (int, float)) else None, large=bool(body.get("large")))
            if channel == "http":
                return self.json({"order": order["orderId"], "channel": "http", **http_post(settings, order)})
            if channel == "avro":
                try:
                    return self.json({"order": order["orderId"], "channel": "avro", **kafkaio.produce_avro(settings, order)})
                except OSError as error:
                    return self.json({"order": order["orderId"], "channel": "avro", "ok": False, "error": f"The schema registry does not answer: {error}"})
            host = body.get("host") if body.get("host") in kafkaio.HOSTS else "orders"
            identity = body.get("identity") if body.get("identity") in kafkaio.IDENTITIES else "fulfillment"
            acks = body.get("acks") if body.get("acks") in kafkaio.ACKS else "all"
            headers = {"x-trace": order["orderId"]} if body.get("trace") else None
            count = body.get("count") if isinstance(body.get("count"), int) and 1 <= body["count"] <= 200 else 1
            items = []
            for n in range(count):
                one = order if n == 0 else orders.make(customer=body.get("customer"), country=body.get("country"))
                if host == "payments":
                    one = {"paymentId": one["orderId"].replace("ORD", "PAY"), "orderId": one["orderId"], "amount": one["amount"], "currency": "EUR", "method": "card"}
                items.append((one["orderId"], dumps(one)))
            result = kafkaio.produce(settings, host, identity, items, acks, headers)
            return self.json({"order": items[0][0] if count == 1 else f"{count} orders", "channel": "kafka", "host": host, "identity": identity, **result})
        if path == "/api/topic":
            body = self.payload()
            name, partitions = str(body.get("name", "")), body.get("partitions", 1)
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", name) or not isinstance(partitions, int) or not 1 <= partitions <= 50:
                raise Refused(400, "A topic name is letters, digits and . _ -, with 1 to 50 partitions")
            host = body.get("host") if body.get("host") in kafkaio.HOSTS else "orders"
            identity = body.get("identity") if body.get("identity") in kafkaio.IDENTITIES else "fulfillment"
            return self.json(kafkaio.create_topic(settings, host, identity, name, partitions))
        if path == "/api/switches":
            body = self.payload()
            wanted = body.get("wanted")
            known = {s["id"]: s for s in SWITCHES}
            if not isinstance(wanted, dict) or not wanted or any(k not in known or not isinstance(v, bool) for k, v in wanted.items()):
                raise Refused(400, "wanted maps a switch to true or false")
            cleared = 0
            if any(known[k].get("clears") and v and not app.management.states().get(k) for k, v in wanted.items()):
                cleared = kafkaio.clear_topics(settings)          # records written in clear cannot be decrypted: the topic starts over
            app.management.set(wanted)
            return self.json({"states": app.management.states(), "cleared": cleared})
        if path == "/api/reset":
            app.management.set({s["id"]: False for s in SWITCHES})
            return self.json({"states": app.management.states(), "cleared": kafkaio.clear_topics(settings)})
        if path == "/api/clear":
            return self.json({"cleared": kafkaio.clear_topics(settings)})
        raise Refused(404, "Not found")

    def status(self, app: App) -> dict:
        """What answers: the gateway, the broker, Azurite and the Management API. Looked at again after four seconds."""
        with app.status_lock:
            if time.monotonic() - app.status_cache.get("at", -99) < 4:
                return app.status_cache["value"]
            settings = app.settings
            value = {}
            try:
                connection = gateway_connection(settings, 2)
                connection.request("GET", "/orders/")
                connection.getresponse().read()
                value["gateway"] = True
            except OSError:
                value["gateway"] = False
            try:
                kafkaio.AdminClient(kafkaio.broker_conf(settings)).list_topics(timeout=2)
                value["broker"] = True
            except Exception:   # noqa: BLE001 - any failure is reported to the person
                value["broker"] = False
            try:
                blobs.listing(settings)
                value["azurite"] = True
            except Exception:   # noqa: BLE001 - any failure is reported to the person
                value["azurite"] = False
            try:
                app.management.call("GET", "/apis?perPage=1")
                value["management"] = True
            except Unavailable:
                value["management"] = False
            app.status_cache.update(at=time.monotonic(), value=value)
            return value


def warm_up(settings: Settings) -> None:
    """The topics, and the container the gateway offloads to, are made as soon as the broker and Azurite answer."""
    for step, name in ((kafkaio.ensure_topics, "The broker"), (blobs.ensure, "Azurite")):
        for _ in range(60):
            try:
                step(settings)
                break
            except Exception:   # noqa: BLE001 - any failure is reported to the person
                time.sleep(2)
        else:
            log.warning("%s did not answer: it is made when it is first used", name)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)       # the SDK writes every request and response at INFO
    try:
        settings = load_settings()
    except SettingsError as error:
        print(f"streams-app: {error}", file=sys.stderr)
        return 2
    app = App(settings=settings, assets=load_assets(), hub=Hub(settings.buffer), management=Management(settings))
    server = Server(("0.0.0.0", settings.port), app)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    threading.Thread(target=warm_up, args=(settings,), daemon=True).start()
    log.info("Demo app on port %d", settings.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
