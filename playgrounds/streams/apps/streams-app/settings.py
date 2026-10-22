"""What the app reads from its environment. A value that cannot be used stops the container with one line that says which."""
import os
from collections.abc import Mapping
from dataclasses import dataclass


class SettingsError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    port: int
    hosts: tuple[str, ...]
    gateway_url: str          # the gateway's HTTP entrypoint, where the HTTP API of the orders is
    orders_key: str           # API key of the Order dashboard application
    kafka_orders: str         # bootstrap of the Orders Kafka API: its host is what the gateway routes on
    kafka_payments: str       # bootstrap of the Payments Kafka API
    broker: str               # the broker itself, plaintext
    orders_topic: str         # the orders topic on the broker
    payments_topic: str
    certs: str                # folder of the client certificates (fulfillment, stranger)
    gateway_cert: str         # the gateway's certificate, which the Kafka clients trust
    management_url: str       # where the policy switches change the APIs
    management_password: str
    partners_bootstrap: str   # bootstrap of the Partners Kafka API, which partners reach with a token of the SSO
    token_url: str            # the SSO's token endpoint, where the partner application gets its tokens
    partner_secret: str       # client secret of the Partner portal application
    registry_url: str         # the schema registry of the Avro orders
    avro_topic: str           # the topic of the Avro orders on the broker
    partner_keys: dict        # API keys of the HTTP partners, by name
    gamma_url: str            # Gravitee Gamma, as the page links to it
    blob_connection: str      # the Azurite account, where large messages are offloaded
    blob_container: str
    buffer: int               # webhook deliveries kept


def _number(env: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a whole number, got a value that is not one") from None
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}")
    return value


def load(env: Mapping[str, str] = os.environ) -> Settings:
    hosts = tuple(h.strip().lower() for h in env.get("ALLOWED_HOSTS", "streams-app,localhost,127.0.0.1,[::1]").split(",") if h.strip())
    if not hosts:
        raise SettingsError("ALLOWED_HOSTS must name at least one host")
    return Settings(
        port=_number(env, "HTTP_PORT", 8000, 1, 65535),
        hosts=hosts,
        gateway_url=env.get("STREAMS_GATEWAY_URL", "http://apim-gateway:8082").rstrip("/"),
        orders_key=env.get("STREAMS_ORDERS_KEY", ""),
        kafka_orders=env.get("STREAMS_KAFKA_ORDERS", "orders.kafka.local:9092"),
        kafka_payments=env.get("STREAMS_KAFKA_PAYMENTS", "payments.kafka.local:9092"),
        broker=env.get("STREAMS_BROKER", "kafka:9091"),
        orders_topic=env.get("STREAMS_BROKER_TOPIC", "acme.orders.v1"),
        payments_topic=env.get("STREAMS_BROKER_PAYMENTS_TOPIC", "acme.payments.v1"),
        certs=env.get("STREAMS_CERTS", "/certs"),
        gateway_cert=env.get("STREAMS_GATEWAY_CERT", "/kafka-certs/kafka-gateway.crt"),
        management_url=env.get("STREAMS_MANAGEMENT_URL", "http://apim-management-api:8083").rstrip("/"),
        management_password=env.get("STREAMS_MANAGEMENT_PASSWORD", ""),
        partners_bootstrap=env.get("STREAMS_KAFKA_PARTNERS", "partners.kafka.local:9092"),
        token_url=env.get("STREAMS_TOKEN_URL", "http://am-gateway:8092/streams/oauth/token"),
        partner_secret=env.get("STREAMS_PARTNER_SECRET", ""),
        registry_url=env.get("STREAMS_REGISTRY_URL", "http://schema-registry:8081").rstrip("/"),
        avro_topic=env.get("STREAMS_AVRO_TOPIC", "acme.orders.avro.v1"),
        partner_keys={"dashboard": env.get("STREAMS_ORDERS_KEY", ""), "france": env.get("STREAMS_PARTNER_FR_KEY", ""), "germany": env.get("STREAMS_PARTNER_DE_KEY", "")},
        gamma_url=env.get("STREAMS_GAMMA_URL", "http://localhost:8086").rstrip("/"),
        blob_connection=env.get("STREAMS_BLOB_CONNECTION", ""),
        blob_container=env.get("STREAMS_BLOB_CONTAINER", "offloaded-orders"),
        buffer=_number(env, "STREAMS_HOOK_BUFFER", 200, 1, 100000),
    )
