# Orders Avro

The same orders as they sit in an **Avro** topic, read as JSON. The producers keep writing Avro and registering their schemas; the gateway reads the schema id at the start of each record, fetches the schema from the registry and answers with plain JSON.

## Call it

Send the key of your subscription in the `X-Gravitee-Api-Key` header. The address is `GATEWAY/orders-avro/`.

| Entrypoint | How to use it |
|---|---|
| HTTP GET | `Accept: application/json` returns the orders that arrived since your last call |
| Server-Sent Events | `Accept: text/event-stream` streams one event per order |

## What the gateway does

- The record is Avro binary, whose first five bytes are the schema id.
- The **Avro to JSON** policy fetches the schema from the registry, once per id.
- The reader gets the order as JSON, with no Avro library and no registry client.
