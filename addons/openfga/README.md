# OpenFGA

An [OpenFGA](https://openfga.dev) server for fine-grained authorization, with its PostgreSQL database and the OpenFGA Playground.

| What | Address |
|---|---|
| Playground | http://localhost:3000/playground |
| HTTP API | http://localhost:8180 |
| gRPC API | `127.0.0.1:8181` |

Inside Docker, the HTTP API is `http://openfga:8180`. The Playground calls the HTTP API from your browser, so keep that address as it is.

OpenFGA runs without authentication (`OPENFGA_AUTHN_METHOD: none`), and every port binds `127.0.0.1`. The database user is `openfga`, and its password is the setting `OPENFGA_POSTGRES_PASSWORD`. The database is reachable inside Docker only.

## Settings

| Setting | Meaning |
|---|---|
| `OPENFGA_VERSION` | OpenFGA version (image tag) |
| `OPENFGA_POSTGRES_VERSION` | PostgreSQL version (image tag) |
| `OPENFGA_POSTGRES_PASSWORD` | Password of the database user `openfga`. Default `openfga`. The database keeps the password it was first created with: set it before the first start, or remove the add-on's data volume, which deletes the stores and models ([how](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/configuration.md#data-and-volumes)) |

## What stays after removal

The stores and models live in the Docker volume `data-openfga`. Stopping the add-on keeps them, and `make reset` deletes them. `gio-openfga-migrate` creates the schema, then exits: it shows as **Done**.
