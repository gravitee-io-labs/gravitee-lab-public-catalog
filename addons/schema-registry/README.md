# Schema Registry

Confluent Schema Registry, on the lab's Kafka broker. Producers register their Avro schemas in it and write records that start with the schema's id; readers fetch the schema by that id. Gravitee's `avro-json` policy reads the registry the same way, so a topic of Avro records can be read as JSON over HTTP.

It includes the [Kafka](../kafka/README.md) add-on, which holds the registry's data in the topic `_schemas`.

## Use it

Inside Docker, the registry is `http://schema-registry:8081`. From your machine it is http://localhost:8097.

```bash
curl -s http://localhost:8097/subjects
```

## Settings

| Setting | Meaning |
|---|---|
| `SCHEMA_REGISTRY_VERSION` | Schema Registry version (image tag) |

## What stays after removal

The schemas live in the Kafka topic `_schemas`, so in the Docker volume `data-kafka-broker`. Stopping keeps them, and `make reset` deletes them.
