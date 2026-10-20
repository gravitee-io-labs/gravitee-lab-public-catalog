"""What the seeder cannot do on API Management 4.12, done through the Console's own API.

- The next-generation developer portal lists the APIs that a navigation item of type API names, in a menu. The seeder fills a whole
  portal (theme, pages, listings) through the Automation API, which 4.12 does not serve yet, so this script puts the two HTTP APIs in a
  menu, with an Overview page each.
- The Kafka Explorer of the Console reads a registered cluster: the lab's broker is registered.

It changes nothing that is already there. seed.sh runs it after the seed, and with --remove before the seed's own removal.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = os.environ["APIM_MANAGEMENT_URL"].rstrip("/") + "/management/v2"
BASE = ROOT + "/organizations/DEFAULT/environments/DEFAULT"
AUTH = "Basic " + base64.b64encode(f"{os.environ['APIM_USERNAME']}:{os.environ['APIM_PASSWORD']}".encode()).decode()
FOLDER = "Event streams"
CLUSTER = "Lab broker"
# The crossId of each API of the menu, and the text of its Overview page
APIS = {"event-streams-orders-events": "/overview-events.md", "event-streams-orders-avro": "/overview-avro.md"}


def call(method, path, body=None, base=BASE):
    request = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": AUTH, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as answer:
            raw = answer.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        raise SystemExit(f"[portal] ✗ {method} {path}: HTTP {error.code} {error.read().decode()[:200]}") from None


def navigation():
    return call("GET", "/portal-navigation-items?" + urllib.parse.urlencode({"area": "TOP_NAVBAR"})).get("items", [])


def publish(item, **changes):
    body = {"type": item["type"], "title": item.get("title", ""), "order": item.get("order", 0), "published": True, "visibility": item.get("visibility", "PUBLIC")}
    for key in ("parentId", "apiId"):
        if item.get(key):
            body[key] = item[key]
    body.update(changes)
    return call("PUT", f"/portal-navigation-items/{item['id']}", body)


def clusters():
    return call("GET", "/clusters", base=ROOT + "/environments/DEFAULT").get("data", [])


def remove():
    """The menu goes with the API items in it, and the registered cluster with it. The APIs are deleted by the seed's own removal."""
    folder = next((i for i in navigation() if i.get("type") == "FOLDER" and i.get("title") == FOLDER), None)
    if folder:
        call("DELETE", f"/portal-navigation-items/{folder['id']}")
        print(f"[portal] ✓ Menu {FOLDER} removed")
    found = next((c for c in clusters() if c.get("name") == CLUSTER), None)
    if found:
        call("DELETE", f"/clusters/{found['id']}", base=ROOT + "/environments/DEFAULT")
        print(f"[portal] ✓ Cluster {CLUSTER} removed")


def menu(apis):
    items = navigation()
    # An API item sits in a folder of the navigation: the folder is a menu of the portal, the portal's catalog lists the APIs in it
    folder = next((i for i in items if i.get("type") == "FOLDER" and i.get("title") == FOLDER), None)
    if not folder:
        folder = call("POST", "/portal-navigation-items", {"type": "FOLDER", "title": FOLDER, "area": "TOP_NAVBAR", "visibility": "PUBLIC", "order": 0})
        print(f"[portal] ✓ Menu {FOLDER} added")
    if not folder.get("published"):
        folder = publish(folder)
    for order, (cross_id, overview) in enumerate(APIS.items()):
        api = apis.get(cross_id)
        if not api:
            raise SystemExit(f"[portal] ✗ the API {cross_id} is not there: the seed did not make it")
        item = next((i for i in items if i.get("type") == "API" and i.get("apiId") == api["id"]), None)
        if not item:
            item = call("POST", "/portal-navigation-items", {"type": "API", "title": "", "area": "TOP_NAVBAR", "visibility": "PUBLIC",
                                                              "apiId": api["id"], "parentId": folder["id"], "order": order})
            print(f"[portal] ✓ {api['name']} added to the catalog")
        if not item.get("published"):
            publish(item)
        # The page an API item opens is its Overview, which the platform makes when it is asked, unpublished
        pages = navigation()
        page = next((i for i in pages if i.get("parentId") == item["id"] and i.get("title") == "Overview"), None)
        if not page:
            call("POST", "/portal-navigation-items/_default-pages", {"ids": [item["id"]]})
            page = next((i for i in navigation() if i.get("parentId") == item["id"] and i.get("title") == "Overview"), None)
        if page:
            text = Path(overview).read_text().replace("GATEWAY", os.environ["APIM_GATEWAY_URL"].rstrip("/"))
            address = f"/portal-page-contents/{page['portalPageContentId']}"
            if call("GET", address).get("content") != text:
                call("PUT", address, {"type": "GRAVITEE_MARKDOWN", "content": text})
                print(f"[portal] ✓ Overview of {api['name']} written")
            if not page.get("published"):
                publish(page)
                print(f"[portal] ✓ Overview of {api['name']} published")


def cluster():
    if not any(c.get("name") == CLUSTER for c in clusters()):
        call("POST", "/clusters", {"type": "KAFKA_CLUSTER_STANDALONE", "name": CLUSTER, "description": "The broker of the lab, which the Explorer reads",
                                   "configuration": {"bootstrapServers": os.environ["STREAMS_BROKER_BOOTSTRAP"], "security": {"protocol": "PLAINTEXT"}}},
             base=ROOT + "/environments/DEFAULT")
        print(f"[portal] ✓ Cluster {CLUSTER} registered")


def main():
    if "--remove" in sys.argv[1:]:
        return remove()
    found = call("GET", "/apis?perPage=100")
    menu({a["crossId"]: a for a in found.get("data", []) if a.get("crossId")})
    cluster()


if __name__ == "__main__":
    sys.exit(main())
