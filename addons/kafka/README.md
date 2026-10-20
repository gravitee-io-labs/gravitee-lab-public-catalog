# Kafka

A single-node Kafka broker (KRaft), Kafka UI, a container with the Kafka command-line tools, and the APIM gateway's native Kafka entrypoint.

The broker image is Bitnami's legacy image, `docker.io/bitnamilegacy/kafka:3.9`, which receives no updates.

## Open it

| What | Address |
|---|---|
| Kafka UI, with the lab's broker already connected | http://localhost:8088 |
| Gateway Kafka entrypoint (TLS) | `127.0.0.1:9092` |
| Broker, plaintext | `127.0.0.1:9091` |
| Broker, SSL | `127.0.0.1:9094` |
| Broker, SASL_PLAINTEXT | `127.0.0.1:9095` |
| Broker, SASL_SSL | `127.0.0.1:9096` |

Every port binds `127.0.0.1`: clients reach the gateway entrypoint only from this machine. Starting the add-on recreates the gateway, which gets the entrypoint.

Inside Docker, the broker is `kafka:9091` (plaintext), and `gio-kafka-client` has the Kafka command-line tools:

```bash
docker exec -it gio-kafka-client bash
```

The broker advertises itself as `kafka`. A client on your machine that connects straight to the broker ports needs `127.0.0.1 kafka` in `/etc/hosts`.

## Reach the gateway from a Kafka client

The entrypoint routes by host name. A client connects to `<api-host>.kafka.local:9092` over TLS, where `<api-host>` is the host of your Kafka API in APIM.

1. Add the names to the hosts file of the machine where the client runs. The lab has one broker, so each API has a bootstrap name and one broker name:

   ```text
   127.0.0.1 my-api.kafka.local broker-0-my-api.kafka.local
   ```

   On macOS and Linux that file is `/etc/hosts`. On Windows with WSL 2, a client that runs on Windows reads `C:\Windows\System32\drivers\etc\hosts` (edit it as an administrator), and a client inside WSL reads the `/etc/hosts` of its distribution.

2. Trust `kafka-gateway.crt`. Copy it out of the client container, then a Java client sets `security.protocol=SSL`, `ssl.truststore.type=PEM`, and that file as `ssl.truststore.location`:

   ```bash
   docker cp gio-kafka-client:/app/.ssl/kafka-gateway.crt .
   ```

## Certificates

The service `kafka-certs` (`gio-kafka-certs`) makes the certificates when the add-on starts, then exits: it shows as **Done**. Only what is missing is made, so they stay the same from one start to the next. They are self-signed and valid for ten years. They are kept on this machine, in the add-on's `.state` folder, which git ignores.

| File | What it is |
|---|---|
| `server.key`, `server.crt` | The broker's key and certificate, for `kafka`, `localhost`, `kafka.local` and `*.kafka.local`. The certificate is also the broker's truststore. A client certificate is requested, not required |
| `kafka-gateway.p12` | The gateway's keystore, with a wildcard certificate for `*.kafka.local`. Its password is `KAFKA_GATEWAY_KEYSTORE_PASSWORD`, `gravitee` by default |
| `kafka-gateway.crt` | The certificate that clients trust, taken from the keystore |

To change the keystore password, set `KAFKA_GATEWAY_KEYSTORE_PASSWORD` in the add-on's settings and apply the change. A keystore keeps the password it was made with, so `kafka-certs` makes the gateway's keystore and certificate again with the new one, and the gateway restarts with it. Clients then need the new `kafka-gateway.crt`. The broker's key and certificate do not change.

## Demo users

The SASL listeners (`9095`, `9096`) enable `PLAIN`, `SCRAM-SHA-256` and `SCRAM-SHA-512`. The client user is `gravitee_user` with the password `gravitee_password`. The other users of the broker are internal. The plaintext listener needs no user.

Each password is a setting: see [Settings](#settings). The broker stores the SCRAM credentials of `gravitee_user` when its data is created, so set `KAFKA_CLIENT_PASSWORD` before the first start, or remove the volume `data-kafka` (the topics go with it): [Data and volumes](https://github.com/dobl1/gravitee-lab/blob/main/docs/configuration.md#data-and-volumes).

## Settings

| Setting | Meaning |
|---|---|
| `KAFKA_VERSION` | Kafka version (image tag) |
| `KAFKA_UI_VERSION` | Kafka UI version (image tag) |
| `KAFKA_CERTS_VERSION` | OpenSSL version (image tag) of the service that makes the certificates |
| `KAFKA_CLIENT_PASSWORD` | Password of the SASL user `gravitee_user`. Default `gravitee_password` |
| `KAFKA_CONTROLLER_PASSWORD` | Password of the broker's controller user, `controller_user`. Default `controller_password` |
| `KAFKA_INTER_BROKER_PASSWORD` | Password of the user the brokers use between them, `inter_broker_user`. Default `inter_broker_password` |
| `KAFKA_GATEWAY_KEYSTORE_PASSWORD` | Password of the gateway's keystore, `kafka-gateway.p12`. Default `gravitee`. See [Certificates](#certificates) |

Choose the versions on the Images page of the Lab UI. The passwords are public demo values: change them in the settings form.

## What stays after removal

The topics live in the Docker volume `data-kafka`. Stopping the add-on keeps them, and `make reset` deletes them. The certificates stay in the add-on's `.state` folder.
