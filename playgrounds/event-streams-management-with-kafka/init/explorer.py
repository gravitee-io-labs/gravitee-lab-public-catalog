"""The connection of Gravitee Gamma's Kafka Explorer to the lab's broker, made through Gamma's own API: the seeder has no module for it.

The Explorer of Event Stream Management browses a Kafka connection: its brokers, its topics, the messages in them and the consumer
groups. The lessons read the broker through it, to see what Kafka really stores. The connection points straight at the broker
(DIRECT_BROKER), in plaintext, as the demo app's Broker column does.

It changes nothing that is already there. seed.sh runs it after the seed, and with --remove before the seed's own removal. A removal
also takes away the cluster that an earlier version of this playground registered in the APIM Console for its Kafka Explorer.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.environ["APIM_MANAGEMENT_URL"].rstrip("/")
EXPLORER = ROOT + "/gamma/organizations/DEFAULT/environments/DEFAULT/modules/esm/kafka-explorer/connections"
CONSOLE_CLUSTERS = ROOT + "/management/v2/environments/DEFAULT/clusters"
AUTH = "Basic " + base64.b64encode(f"{os.environ['APIM_USERNAME']}:{os.environ['APIM_PASSWORD']}".encode()).decode()
NAME = "Lab broker"


def call(method, url, body=None, missing_ok=False):
    request = urllib.request.Request(url, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": AUTH, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as answer:
            raw = answer.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        if missing_ok and error.code == 404:
            return {}
        raise SystemExit(f"[explorer] ✗ {method} {url[len(ROOT):]}: HTTP {error.code} {error.read().decode()[:200]}") from None


def connections():
    return call("GET", EXPLORER + "?page=1&perPage=100").get("data", [])


def make():
    if any(c.get("name") == NAME for c in connections()):
        return
    call("POST", EXPLORER, {"name": NAME, "description": "The lab's broker, read with no gateway in between: what Kafka really stores",
                            "target": {"type": "DIRECT_BROKER", "bootstrapServers": os.environ["STREAMS_BROKER_BOOTSTRAP"]}})
    print(f"[explorer] ✓ Connection {NAME} made")


def remove():
    for connection in connections():
        if connection.get("name") == NAME:
            call("DELETE", f"{EXPLORER}/{connection['id']}")
            print(f"[explorer] ✓ Connection {NAME} removed")
    # The cluster of the APIM Console, which an earlier version of the playground registered for the Console's Kafka Explorer
    for cluster in call("GET", CONSOLE_CLUSTERS, missing_ok=True).get("data", []):
        if cluster.get("name") == NAME:
            call("DELETE", f"{CONSOLE_CLUSTERS}/{cluster['id']}", missing_ok=True)
            print(f"[explorer] ✓ Console cluster {NAME} removed")


if __name__ == "__main__":
    sys.exit(remove() if "--remove" in sys.argv[1:] else make())
