"""The policy switches: each one turns steps of an API's flow on or off through the Management API and deploys the API,
which is what a person does in the Console's Policy Studio. The plans, and so the subscriptions, are not touched."""
import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from settings import Settings

PATH = "/management/v2/organizations/DEFAULT/environments/DEFAULT"
PHASES = ("request", "response", "publish", "subscribe", "interact", "connect")
READ_ONLY = {"id", "deployedAt", "createdAt", "updatedAt", "state", "primaryOwner", "originContext", "links", "_links",
             "deploymentState", "workflowState", "lifecycleState", "definitionContext"}
GATEWAY_SYNC_S = 7          # the gateway looks for new deployments every few seconds

SWITCHES = [
    {"id": "http-filter", "api": "Orders Events", "steps": ["Only high-value orders"], "group": "HTTP",
     "label": "High-value only", "hint": "Message filtering drops the orders under 500 before any reader gets them"},
    {"id": "http-reshape", "api": "Orders Events", "steps": ["Notification payload"], "group": "HTTP",
     "label": "Reshape", "hint": "JSON to JSON drops the email and the card and renames the amount"},
    {"id": "avro-json", "api": "Orders Avro", "steps": ["Avro to JSON"], "group": "Avro",
     "label": "Avro to JSON", "hint": "The gateway reads the schema in the registry and answers in JSON"},
    {"id": "kafka-filter", "api": "Orders Kafka", "steps": ["Only high-value orders"], "group": "Kafka",
     "label": "High-value only", "hint": "Kafka message filtering drops the orders under 500 on the way to the consumer"},
    {"id": "kafka-encrypt", "api": "Orders Kafka", "steps": ["Encrypt card and email", "Decrypt card and email"], "group": "Kafka",
     "label": "Encrypt", "hint": "AES-256-GCM on two fields before Kafka stores them, decrypted for the consumer", "clears": True},
    {"id": "kafka-offload", "api": "Orders Kafka", "steps": ["Offload large orders", "Fetch offloaded orders"], "group": "Kafka",
     "label": "Offload", "hint": "Orders over 50 KB go to Azurite, the record keeps a pointer"},
    {"id": "guardrails", "api": "Orders Kafka", "steps": ["Topic guardrails"], "group": "Rules",
     "label": "Topic guardrails", "hint": "A new topic is named orders-something in lower case and has at most 3 partitions"},
    {"id": "safe-producers", "api": "Orders Kafka", "steps": ["Safe producers"], "group": "Rules",
     "label": "Safe producers", "hint": "No acks=0, and every record carries an x-trace header"},
    {"id": "quota", "api": "Orders Kafka", "steps": ["Byte quota", "Byte quota (read)"], "group": "Rules",
     "label": "Byte quota", "hint": "4 KB a second to write and 4 KB a second to read, then the gateway tells the client to slow down"},
]


class Unavailable(Exception):
    pass


# The Explorer of Gamma's Event Stream Management, and the connection to the lab's broker that the seed makes in it
EXPLORER = "/gamma/organizations/DEFAULT/environments/DEFAULT/modules/esm/kafka-explorer/connections"
EXPLORER_CONNECTION = "Lab broker"


class Management:
    def __init__(self, settings: Settings, opener: Callable = urllib.request.urlopen) -> None:
        self.base = settings.management_url + PATH
        self.auth = "Basic " + base64.b64encode(f"admin:{settings.management_password}".encode()).decode()
        self.open = opener
        self.lock = threading.Lock()
        self.ids: dict[str, str] = {}

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(self.base + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                         headers={"Authorization": self.auth, "Content-Type": "application/json"})
        try:
            with self.open(request, timeout=15) as answer:
                raw = answer.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            raise Unavailable(f"The Management API answered {error.code} to {method} {path}") from None
        except (urllib.error.URLError, OSError) as error:
            raise Unavailable(f"Cannot reach the Management API: {error}") from None

    def api_id(self, name: str) -> str:
        if name not in self.ids:
            found = self.call("GET", "/apis?perPage=50&q=" + urllib.parse.quote(name))
            match = next((a["id"] for a in found.get("data", []) if a["name"] == name), None)
            if not match:
                raise Unavailable(f"The API {name} does not exist yet: the seed has not run")
            self.ids[name] = match
        return self.ids[name]

    def steps(self, api: dict, names: list[str]) -> list[dict]:
        return [step for flow in api.get("flows") or [] for phase in PHASES for step in flow.get(phase) or [] if step.get("name") in names]

    def states(self) -> dict[str, bool | None]:
        """Whether each switch is on: all its steps are enabled. None when its API is not there."""
        cache: dict[str, dict] = {}
        out: dict[str, bool | None] = {}
        for switch in SWITCHES:
            try:
                api = cache.get(switch["api"]) or cache.setdefault(switch["api"], self.call("GET", "/apis/" + self.api_id(switch["api"])))
            except Unavailable:
                out[switch["id"]] = None
                continue
            steps = self.steps(api, switch["steps"])
            out[switch["id"]] = bool(steps) and all(step.get("enabled") for step in steps)
        return out

    def set(self, wanted: dict[str, bool]) -> None:
        """Brings the switches to the states asked for, one update and one deployment for each API that changes."""
        with self.lock:
            by_api: dict[str, dict[str, bool]] = {}
            for switch in SWITCHES:
                if switch["id"] in wanted:
                    by_api.setdefault(switch["api"], {}).update({step: wanted[switch["id"]] for step in switch["steps"]})
            for name, steps in by_api.items():
                identifier = self.api_id(name)
                api = self.call("GET", "/apis/" + identifier)
                changed = False
                for step in self.steps(api, list(steps)):
                    if step.get("enabled") != steps[step["name"]]:
                        step["enabled"], changed = steps[step["name"]], True
                if not changed:
                    continue
                self.call("PUT", "/apis/" + identifier, {k: v for k, v in api.items() if k not in READ_ONLY})
                self.call("POST", f"/apis/{identifier}/deployments", {"deploymentLabel": "Policy switch"})
                self.wait_deployed(identifier)

    def links(self, settings: Settings) -> dict:
        """What the page links to in Gravitee Gamma: the ids of the APIs and of the Explorer's connection to the broker."""
        found: dict = {"gamma": settings.gamma_url, "apis": {}, "explorer": None}
        for name in ("Orders Events", "Orders Avro", "Orders Kafka", "Partners Kafka", "Payments Kafka"):
            try:
                found["apis"][name] = self.api_id(name)
            except Unavailable:
                pass
        try:
            base = settings.management_url + EXPLORER + "?page=1&perPage=50"
            request = urllib.request.Request(base, headers={"Authorization": self.auth})
            with self.open(request, timeout=10) as answer:
                connections = json.loads(answer.read()).get("data", [])
            found["explorer"] = next((c["id"] for c in connections if c.get("name") == EXPLORER_CONNECTION), None)
        except (urllib.error.URLError, OSError, ValueError):
            pass
        return found

    def wait_deployed(self, identifier: str) -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.call("GET", "/apis/" + identifier).get("deploymentState") == "DEPLOYED":
                break
            time.sleep(0.5)
        time.sleep(GATEWAY_SYNC_S)
