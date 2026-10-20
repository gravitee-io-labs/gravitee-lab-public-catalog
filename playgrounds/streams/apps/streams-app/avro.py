"""The Avro orders: what a legacy Kafka producer writes. The schema is in the registry, each record starts with its id (Confluent wire format)."""
import io
import json
import struct
import urllib.request

import fastavro

from settings import Settings

SCHEMA = {
    "type": "record", "name": "Order", "namespace": "io.acme.shop",
    "fields": [{"name": n, "type": t} for n, t in (
        ("orderId", "string"), ("customer", "string"), ("email", "string"), ("country", "string"),
        ("amount", "double"), ("currency", "string"), ("card", "string"), ("status", "string"))],
}
PARSED = fastavro.parse_schema(SCHEMA)
_ids: dict[str, int] = {}


def subject(settings: Settings) -> str:
    return f"{settings.avro_topic}-value"


def register(settings: Settings) -> int:
    """The schema's id in the registry: registered the first time, the same id afterwards."""
    if settings.registry_url not in _ids:
        request = urllib.request.Request(f"{settings.registry_url}/subjects/{subject(settings)}/versions", method="POST",
                                         data=json.dumps({"schema": json.dumps(SCHEMA)}).encode(),
                                         headers={"Content-Type": "application/vnd.schemaregistry.v1+json"})
        with urllib.request.urlopen(request, timeout=5) as answer:
            _ids[settings.registry_url] = json.load(answer)["id"]
    return _ids[settings.registry_url]


def encode(order: dict, schema_id: int) -> bytes:
    """Magic byte 0, the schema id on four bytes, then the Avro binary of the record."""
    out = io.BytesIO()
    out.write(b"\x00" + struct.pack(">I", schema_id))
    fastavro.schemaless_writer(out, PARSED, {k: order[k] for k in (f["name"] for f in SCHEMA["fields"])})
    return out.getvalue()


def schema_id_of(value: bytes) -> int | None:
    """The schema id a record starts with, when it is in the wire format."""
    return struct.unpack(">I", value[1:5])[0] if len(value) > 5 and value[0] == 0 else None
