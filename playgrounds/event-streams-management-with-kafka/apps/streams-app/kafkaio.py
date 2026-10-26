"""The Kafka side of the app: a client of the gateway's native Kafka APIs, a client of the broker itself, and the TLS look at the
gateway's one Kafka port.

A gateway client proves who it is the way the API's plan asks: a certificate (mTLS) for Orders and Payments, a token of the SSO
(OAUTHBEARER) for Partners. It names the host of the API in the TLS handshake (SNI). The broker client bypasses the gateway on
purpose: it shows what Kafka really stores.
"""
import logging
import socket
import ssl
import struct
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

from confluent_kafka import Consumer, KafkaError, Producer, TopicPartition
from confluent_kafka.admin import AdminClient, NewTopic

import avro
from settings import Settings
from shown import shorten

CERT_IDENTITIES = ("fulfillment", "billing", "stranger")
IDENTITIES = CERT_IDENTITIES + ("anonymous", "partner")
HOSTS = ("orders", "payments", "partners")
HIDDEN_TOPICS = ("__consumer_offsets",)
REPLAY = 6                  # records of each topic the broker view starts with
ACKS = {"all": "all", "leader": "1", "none": "0"}
PARTNER_CLIENT_ID = "partner-portal"


class Capture(logging.Handler):
    """Keeps what librdkafka says while a client works, so that a refused connection can say why."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def capturing() -> tuple[logging.Logger, Capture]:
    logger = logging.getLogger(f"rdkafka.{uuid.uuid4().hex[:8]}")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = Capture()
    logger.addHandler(handler)
    return logger, handler


def explain(lines: list[str], identity: str, fallback: str = "", host: str = "orders") -> str:
    """What went wrong in words: the TLS conversation with the gateway, or its answer, says it in a line."""
    text = " ".join(lines) + " " + fallback
    closed = "SSL connection closed by peer" in text or "certificate required" in text or "CERTIFICATE_REQUIRED" in text
    if identity == "anonymous" and closed:
        need = "a token of the SSO" if host == "partners" else "a client certificate (mTLS plan)"
        return f"The gateway closed the connection: this API needs {need} and none came"
    if identity == "stranger" and ("closed by peer" in text or "Disconnected" in text):
        return "The gateway closed the connection after the handshake: no application of the Orders Kafka API has registered this certificate"
    if identity == "partner" and ("invalid_client" in text or "retrieve OIDC token" in text):
        return "The SSO refused the application's id or secret, so there is no token to present"
    if "already exists" in text:
        return "The topic exists already: the rules let this name through"
    if "Policy violation" in text or "POLICY_VIOLATION" in text:
        return "A rule of the gateway refused the request (policy violation): the gateway's log says which one"
    if "uthorization failed" in text or "TOPIC_AUTHORIZATION_FAILED" in text:
        return "The Kafka ACL of the API refuses this: the identity may not do that on this topic"
    if "certificate verify failed" in text or "verification failed" in text:
        return "This client does not trust the gateway's certificate: it needs kafka-gateway.crt as its truststore"
    if "Name or service not known" in text or "Failed to resolve" in text:
        return "The host name does not resolve: add it to the hosts file of the machine where the client runs"
    return fallback or "Cannot reach the gateway's Kafka port"


def bootstrap(settings: Settings, host: str) -> str:
    return {"orders": settings.kafka_orders, "payments": settings.kafka_payments, "partners": settings.partners_bootstrap}[host]


def topic_of(host: str) -> str:
    return "payments" if host == "payments" else "orders"      # the client-side name of the topic: Partners reads the orders too


def gateway_conf(settings: Settings, host: str, identity: str) -> dict:
    conf = {
        "bootstrap.servers": bootstrap(settings, host),
        "security.protocol": "ssl",
        "ssl.ca.location": settings.gateway_cert,
        "socket.connection.setup.timeout.ms": 6000,
        "reconnect.backoff.max.ms": 2000,
    }
    if identity in CERT_IDENTITIES:
        conf["ssl.certificate.location"] = str(Path(settings.certs) / f"{identity}.crt")
        conf["ssl.key.location"] = str(Path(settings.certs) / f"{identity}.key")
    elif identity == "partner":
        conf.update({
            "security.protocol": "sasl_ssl", "sasl.mechanisms": "OAUTHBEARER", "sasl.oauthbearer.method": "oidc",
            "sasl.oauthbearer.client.id": PARTNER_CLIENT_ID, "sasl.oauthbearer.client.secret": settings.partner_secret,
            "sasl.oauthbearer.token.endpoint.url": settings.token_url,
        })
    return conf


def broker_conf(settings: Settings) -> dict:
    return {"bootstrap.servers": settings.broker, "security.protocol": "plaintext"}


def broker_topics(settings: Settings) -> tuple[str, str, str]:
    return (settings.orders_topic, settings.payments_topic, settings.avro_topic)


def text(raw: bytes | None) -> str:
    return "" if raw is None else raw.decode("utf-8", errors="replace")


def record(message) -> dict:
    value = message.value() or b""
    out = {
        "type": "message", "topic": message.topic(), "partition": message.partition(), "offset": message.offset(),
        "key": text(message.key()), "size": len(value),
        "headers": [[k, text(v)] for k, v in (message.headers() or [])],
    }
    schema = avro.schema_id_of(value)
    if schema is not None:
        out.update(value=" ".join(f"{b:02x}" for b in value[:40]) + (" …" if len(value) > 40 else ""), binary=True, schema=schema)
    else:
        out["value"] = shorten(text(value))
    return out


# --- Producing through the gateway ------------------------------------------------------------------------------------

def produce(settings: Settings, host: str, identity: str, items: list[tuple[str, bytes]], acks: str = "all", headers: dict | None = None) -> dict:
    """Records through the gateway's native Kafka API, over one connection. {ok, ...}: the partition and offset of the last one, or why it was refused."""
    logger, captured = capturing()
    outcome: dict = {"delivered": 0}
    throttled: list[int] = []
    started = time.monotonic()

    def delivered(error, message) -> None:
        if error is not None:
            outcome["error"] = str(error)
        else:
            outcome.update(partition=message.partition(), offset=message.offset(), topic=message.topic(), delivered=outcome["delivered"] + 1)

    conf = gateway_conf(settings, host, identity) | {
        "message.timeout.ms": 8000, "acks": ACKS.get(acks, "all"), "log_level": 6, "debug": "security,broker",
        "throttle_cb": lambda event: throttled.append(round(event.throttle_time * 1000)),
    }
    producer = Producer(conf, logger=logger)
    for key, value in items:
        producer.produce(topic_of(host), key=key.encode(), value=value, headers=list((headers or {}).items()) or None, on_delivery=delivered)
    producer.flush(20)
    took = round((time.monotonic() - started) * 1000)
    extra = {"throttle_ms": max(throttled)} if throttled else {}
    if acks == "none" and "error" not in outcome:
        return {"ok": True, "ms": took, "unacknowledged": True, **extra}      # acks=0: the client never hears of a refusal
    if outcome["delivered"] and "error" not in outcome:
        return {"ok": True, "ms": took, **outcome, **extra}
    return {"ok": False, "ms": took, "error": explain(captured.lines, identity, outcome.get("error", ""), host), "detail": outcome.get("error", ""), **extra}


def create_topic(settings: Settings, host: str, identity: str, name: str, partitions: int) -> dict:
    """Asks the gateway to create a topic, as a team would with its own tools."""
    logger, captured = capturing()
    admin = AdminClient(gateway_conf(settings, host, identity) | {"socket.timeout.ms": 8000, "request.timeout.ms": 8000, "logger": logger})
    try:
        futures = admin.create_topics([NewTopic(name, num_partitions=partitions, replication_factor=1)], request_timeout=8, operation_timeout=8)
        futures[name].result(timeout=10)
        return {"ok": True, "topic": name, "partitions": partitions}
    except Exception as error:   # noqa: BLE001 - any failure is reported to the person
        detail = str(error)
        return {"ok": False, "error": explain(captured.lines, identity, detail, host), "detail": detail[:160]}


# --- Tails --------------------------------------------------------------------------------------------------------------

def tail_gateway(settings: Settings, host: str, identity: str, from_beginning: bool) -> Iterator[dict | None]:
    """The records of a topic as the gateway hands them to a native Kafka consumer. None is a beat of nothing to say."""
    logger, captured = capturing()
    errors: list[str] = []
    conf = gateway_conf(settings, host, identity) | {
        "group.id": f"streams-app-{uuid.uuid4().hex[:8]}", "enable.auto.commit": False,
        "auto.offset.reset": "earliest" if from_beginning else "latest", "session.timeout.ms": 6000,
        "log_level": 6, "debug": "security,broker",
        "error_cb": lambda e: errors.append(f"{e.str()}: the client reconnects" if e.code() in (KafkaError._TRANSPORT, KafkaError._ALL_BROKERS_DOWN) else str(e)),
    }
    consumer = Consumer(conf, logger=logger)
    assigned = threading.Event()
    consumer.subscribe([topic_of(host)], on_assign=lambda c, partitions: assigned.set())
    yield {"type": "status", "message": f"Connecting to {bootstrap(settings, host)} as {identity}"}
    announced = False
    try:
        while True:
            message = consumer.poll(1.0)
            if assigned.is_set() and not announced:
                announced = True
                yield {"type": "status", "ready": True, "message": f"Listening on {topic_of(host)}: the consumer group has its partition"}
            if errors:
                yield {"type": "error", "transient": identity in ("fulfillment", "billing", "partner"), "message": explain(captured.lines, identity, errors[-1], host)}
                errors.clear()
                captured.lines.clear()
            if message is None:
                yield None
                continue
            if message.error():
                if message.error().code() != KafkaError._PARTITION_EOF:
                    yield {"type": "error", "message": explain(captured.lines, identity, str(message.error()), host)}
                continue
            yield record(message)
    finally:
        consumer.close()


def topics_present(client: AdminClient, wanted: tuple[str, ...]) -> dict[str, int]:
    """The wanted topics that exist, with their number of partitions."""
    metadata = client.list_topics(timeout=3)
    return {name: len(metadata.topics[name].partitions) for name in wanted if name in metadata.topics and not metadata.topics[name].error}


def tail_broker(settings: Settings) -> Iterator[dict | None]:
    """The records of the orders, payments and Avro topics straight from the broker, starting with the last few of each."""
    wanted = broker_topics(settings)
    admin = AdminClient(broker_conf(settings))
    consumer = Consumer(broker_conf(settings) | {"group.id": f"streams-app-broker-{uuid.uuid4().hex[:8]}", "enable.auto.commit": False,
                                                   "auto.offset.reset": "latest", "session.timeout.ms": 6000})
    assigned: set[str] = set()
    last_look = 0.0
    yield {"type": "status", "message": f"Reading {', '.join(wanted)} straight from the broker at {settings.broker}"}
    try:
        while True:
            if time.monotonic() - last_look > 2 and len(assigned) < len(wanted):
                last_look = time.monotonic()
                try:
                    found = topics_present(admin, wanted)
                except Exception:      # noqa: BLE001 - the broker is not answering yet: look again
                    found = {}
                fresh = [name for name in found if name not in assigned]
                if fresh:
                    partitions = []
                    for name in fresh:
                        for partition in range(found[name]):
                            low, high = consumer.get_watermark_offsets(TopicPartition(name, partition), timeout=3)
                            partitions.append(TopicPartition(name, partition, max(low, high - REPLAY)))
                        assigned.add(name)
                    consumer.assign(consumer.assignment() + partitions)
            message = consumer.poll(1.0)
            if message is None:
                yield None
            elif message.error():
                if message.error().code() not in (KafkaError._PARTITION_EOF, KafkaError.UNKNOWN_TOPIC_OR_PART):
                    yield {"type": "error", "message": str(message.error())}
            else:
                yield record(message)
    finally:
        consumer.close()


# --- The topics themselves ---------------------------------------------------------------------------------------------

RETENTION_MS = str(24 * 60 * 60 * 1000)      # a day: the topics are for a demo, and a reader that starts from the beginning reads a day at most


def ensure_topics(settings: Settings) -> None:
    """The orders, payments and Avro topics exist before the first record, so that a client sees them from the start."""
    admin = AdminClient(broker_conf(settings))
    wanted = broker_topics(settings)
    missing = [name for name in wanted if name not in topics_present(admin, wanted)]
    for name, future in admin.create_topics([NewTopic(n, num_partitions=1, replication_factor=1, config={"retention.ms": RETENTION_MS}) for n in missing]).items():
        try:
            future.result(timeout=10)
        except Exception as error:
            if "TOPIC_ALREADY_EXISTS" not in str(error):
                raise


def clear_topics(settings: Settings) -> int:
    """Deletes every record of the orders, payments and Avro topics on the broker, and the topics that lessons created. How many records went."""
    wanted = broker_topics(settings)
    admin = AdminClient(broker_conf(settings))
    consumer = Consumer(broker_conf(settings) | {"group.id": f"streams-app-clear-{uuid.uuid4().hex[:8]}"})
    gone, targets = 0, []
    try:
        for name, partitions in topics_present(admin, wanted).items():
            for partition in range(partitions):
                low, high = consumer.get_watermark_offsets(TopicPartition(name, partition), timeout=3)
                gone += high - low
                targets.append(TopicPartition(name, partition, high))
    finally:
        consumer.close()
    if targets:
        for future in admin.delete_records(targets).values():
            future.result(timeout=10)
    # The topics a lesson asked the gateway to create (orders-eu...) go too, so that the lesson starts over as the first time
    extra = [name for name in admin.list_topics(timeout=3).topics if name.startswith(f"{topic_of('orders')}-") and name not in wanted]
    for future in (admin.delete_topics(extra, operation_timeout=8).values() if extra else []):
        future.result(timeout=10)
    return gone


def produce_avro(settings: Settings, order: dict) -> dict:
    """A legacy producer: it writes the order in Avro, with its schema id, straight to the broker."""
    schema_id = avro.register(settings)
    started = time.monotonic()
    producer = Producer(broker_conf(settings) | {"message.timeout.ms": 8000})
    outcome: dict = {}

    def delivered(error, message) -> None:
        outcome.update(error=str(error)) if error is not None else outcome.update(partition=message.partition(), offset=message.offset())

    producer.produce(settings.avro_topic, key=order["orderId"].encode(), value=avro.encode(order, schema_id), on_delivery=delivered)
    producer.flush(10)
    took = round((time.monotonic() - started) * 1000)
    if "offset" in outcome:
        return {"ok": True, "ms": took, "schema": schema_id, **outcome}
    return {"ok": False, "ms": took, "error": outcome.get("error", "The broker did not answer")}


# --- The look at the gateway's Kafka port ------------------------------------------------------------------------------

def api_versions_request() -> bytes:
    """The first thing every Kafka client says: an ApiVersions request (key 18, version 0)."""
    client_id = b"streams-app-probe"
    body = struct.pack(">hhih", 18, 0, 1, len(client_id)) + client_id
    return struct.pack(">i", len(body)) + body


def probe(settings: Settings, host: str, identity: str = "fulfillment") -> dict:
    """A TLS handshake with the gateway's Kafka port that names `host` in the ClientHello, and what the gateway does next.

    The same port and the same address answer every API: the name in the handshake picks it. A name no API has gets a
    certificate all the same, and then nothing."""
    name = f"{host}.kafka.local"
    result: dict = {"sni": name, "tls": None, "kafka": None, "topics": None, "brokers": None}
    context = ssl.create_default_context(cafile=settings.gateway_cert)
    certificate, key = Path(settings.certs) / f"{identity}.crt", Path(settings.certs) / f"{identity}.key"
    if identity in CERT_IDENTITIES and certificate.exists():
        context.load_cert_chain(str(certificate), str(key))
    gateway = settings.kafka_orders.rsplit(":", 1)[0]
    port = int(settings.kafka_orders.rsplit(":", 1)[1])
    try:
        with socket.create_connection((gateway, port), timeout=5) as raw, context.wrap_socket(raw, server_hostname=name) as tls:
            peer = tls.getpeercert()
            result["tls"] = {
                "ok": True, "protocol": tls.version(), "cipher": tls.cipher()[0],
                "subject": ", ".join(f"{k}={v}" for rdn in peer.get("subject", ()) for k, v in rdn),
                "san": [value for _, value in peer.get("subjectAltName", ())],
            }
            tls.settimeout(4)
            try:
                tls.sendall(api_versions_request())
                answer = tls.recv(4)
                result["kafka"] = "answered" if len(answer) == 4 else "closed"
            except (OSError, ssl.SSLError):
                result["kafka"] = "closed"
    except (OSError, ssl.SSLError) as error:
        result["tls"] = {"ok": False, "error": str(error)}
    if host in HOSTS:
        who = "partner" if host == "partners" else "fulfillment"
        try:
            metadata = AdminClient(gateway_conf(settings, host, who)).list_topics(timeout=6)
            result["topics"] = sorted(n for n in metadata.topics if n not in HIDDEN_TOPICS)
            result["brokers"] = [f"{b.host}:{b.port}" for b in metadata.brokers.values()]
        except Exception as error:   # noqa: BLE001 - any failure is reported to the person
            result["topics"], result["error"] = [], str(error)
    return result
