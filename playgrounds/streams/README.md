# Event Streams Management with Kafka

A Kafka topic of orders, put in front of its consumers by Gravitee two ways.

- **Protocol mediation** turns the topic into an HTTP POST, a GET, an SSE stream and a webhook that people subscribe to in the Developer Portal. It shapes the stream with message filtering and JSON to JSON, gives each partner its own view of one topic, and reads an Avro topic as JSON.
- **Native Kafka** lets plain Kafka clients connect through the gateway: routed by host name (SNI), identified by a certificate (mTLS) or a token (SSO), governed by rules on topics, producers and quotas, and watched in the dashboards and logs of Gravitee Gamma. The payload is encrypted and large records are offloaded to an object store.

The guide has twelve lessons and takes about 70 minutes. Each one opens with the situation, then what Gravitee does about it, then buttons to try it and to see it in **Gravitee Gamma**: the APIs and their policies, the logs, the dashboards and the Explorer of the broker.

## Needs

- API Management **4.13.0-alpha.6 or later**, a pre-release whose Gamma has the Message APIs, Observability and Explorer of Event Stream Management (4.12 has none of them). It needs the **Native Kafka** and **Event-native** license packs, and the Lab UI says when the license lacks a feature.
- The plugin `gravitee-resource-storage-azure-blob`, which Start installs. The Kafka Offloading policy stores records in Azure Blob Storage only, so the **Azurite** add-on stands in for it.
- The add-ons **Kafka**, **Azurite** and **Schema Registry**, which Start turns on. Access Management comes with the platform and is the identity provider of the partner SSO.
- Enough memory for the platform, a broker and a few small apps.

## Start it

Open it on the Playgrounds page of the Lab UI and select Start. The first start builds two images and makes the certificates. The seed then creates, in the platform's own environment:

| What | Detail |
|---|---|
| **Orders Events** | A message API on `/orders/`: HTTP POST, HTTP GET, SSE and webhook entrypoints over the Kafka topic `acme.orders.v1`. Plans **API key**, **Webhook**, **France** and **Germany** (the last two filter the stream by country). Listed in the next-generation Developer Portal |
| **Orders Avro** | A message API on `/orders-avro/` over a topic of Avro records, read as JSON once the policy is on. Listed in the Developer Portal |
| **Orders Kafka** | A native Kafka API on the host `orders`, plan **mTLS**. It holds every policy of lessons 9 to 12, switched off |
| **Payments Kafka** | A second native Kafka API on the host `payments`, to show routing by host name |
| **Partners Kafka** | A third native Kafka API on the host `partners`, plan **SSO token** (JWT), read only |
| Applications | **Order dashboard**, **Partner France** and **Partner Germany** (API keys), **Order notifier** (webhook), **Fulfillment service** and **Billing service** (client certificates), **Partner portal** (token) |
| Access Management | A domain `streams` with the application **Partner portal**, which gets the tokens |

The policies of the lessons are on the APIs from the start, switched off. The **Demo App** tab has a switch for each one, which updates the API and deploys it. *Reset* in the app puts them all off, clears the topics and deletes the topics that lessons created.

## Open it

| What | Address |
|---|---|
| Demo App, the demo application | http://localhost:8170 |
| Developer Portal (next generation) | http://localhost:8085/next/ |
| Gravitee Gamma | http://localhost:8086 |
| AM Console | http://localhost:8081 |
| Schema Registry | http://localhost:8097 |
| Gateway, HTTP | http://localhost:8082 |
| Gateway, Kafka | `orders.kafka.local:9092`, `payments.kafka.local:9092`, `partners.kafka.local:9092` |

Sign in to Gamma, the AM Console and the Developer Portal as `admin`; the **Details** tab of the playground lists the passwords, the API keys and the client secret of the lessons.

## Use a Kafka client from your machine

The demo app and the terminal run inside Docker, where the host names of the Kafka APIs already resolve. A client on your machine needs them in its hosts file, pointing at the gateway's Kafka port, which is published on `127.0.0.1:9092`:

```text
127.0.0.1 orders.kafka.local broker-0-orders.kafka.local payments.kafka.local broker-0-payments.kafka.local partners.kafka.local broker-0-partners.kafka.local
```

It trusts the gateway's certificate and presents the fulfillment service's, which you copy out of the terminal container:

```bash
docker cp gio-streams-tools:/kafka-certs/kafka-gateway.crt .
docker cp gio-streams-tools:/certs/fulfillment.crt .
docker cp gio-streams-tools:/certs/fulfillment.key .
```

```bash
kcat -b orders.kafka.local:9092 -C -t orders -o beginning -e \
  -X security.protocol=ssl -X ssl.ca.location=kafka-gateway.crt \
  -X ssl.certificate.location=fulfillment.crt -X ssl.key.location=fulfillment.key
```

## Settings

| Setting | Meaning |
|---|---|
| `STREAMS_APIM_PASSWORD` | Password of user `admin` in API Management, which the seed and the app's switches sign in with. Default `admin` |
| `STREAMS_AM_PASSWORD` | Password of user `admin` in Access Management, which the seed signs in with. Default `adminadmin` |
| `STREAMS_ORDERS_KEY` | API key of the **Order dashboard** application. Set it before the first start: the seed gives the subscription this key and keeps it afterwards |
| `STREAMS_PARTNER_FR_KEY`, `STREAMS_PARTNER_DE_KEY` | API keys of **Partner France** and **Partner Germany**, on their plans of the Orders Events API. Same rule as the dashboard's |
| `STREAMS_PARTNER_SECRET` | Client secret of the **Partner portal** application in Access Management, with which it gets its tokens |
| `STREAMS_ENCRYPTION_KEY` | Base64 AES-256 key of the encryption policy. A new value, applied with Re-seed, makes the records already encrypted unreadable |
| `STREAMS_BLOB_ACCOUNT_KEY` | Base64 key of the Azurite account `devstoreaccount1`, with which the gateway signs what it offloads. A demo value by default |
| `STREAMS_BLOB_CONNECTION_STRING` | Connection string of the Azurite account where large records are offloaded. It carries the key above by default |
| `STREAMS_PULL_POLICY` | `build` builds the images here at each start, `always` pulls them |
| `STREAMS_OPENSSL_VERSION`, `STREAMS_SOCAT_VERSION` | Image tags of the certificate one-shot and of the host names forwarder |

## What changes in the platform

- The gateway gets `kafka.ssl.clientAuth=request`: it asks every Kafka client for a certificate but does not require one. The **mTLS** plans refuse a client without a registered certificate, and the **SSO token** plan accepts a client with none. It applies to **every** native Kafka API on the gateway while this playground is on.
- The orders APIs are added to the catalog of the next-generation Developer Portal (a menu *Event streams*, with an Overview page for each API), which the seed cannot do through the Automation API on 4.12.
- The seed adds a connection named *Lab broker* to Gamma's Explorer, which reads the broker directly, for lessons 2, 7, 11 and 12.
- The webhook entrypoint of Orders Events records each delivery, which Gamma lists under **Webhooks**.

## What stays after removal

The certificates live in the Docker volume `data-streams-certs`, the blobs in `data-azurite` and the topics and schemas in `data-kafka`. Stopping keeps them, and `make reset` deletes them. *Delete what it created* in the Lab UI removes the APIs, the applications, the Access Management domain, the portal menu and the Explorer connection.

## Share it

The playground includes the add-ons **Kafka**, **Azurite** and **Schema Registry**, so a catalog that takes it takes them too. It builds two images, `streams-app` and `streams-tools`, named for the public catalog's image prefix. Another catalog asks for its own.
