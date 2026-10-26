# OpenFGA

An [OpenFGA](https://openfga.dev) server for fine-grained authorization, with its PostgreSQL database and the OpenFGA Playground.

## Needs

Nothing more than the platform.

## Ports

| Port | What it is | Login |
|---|---|---|
| 3000 | The Playground, http://localhost:3000/playground | None |
| 8180 | The HTTP API, http://localhost:8180 (`http://openfga:8180` inside Docker) | None |
| 8181 | The gRPC API, `127.0.0.1:8181` | None |

Every port binds `127.0.0.1`. The Playground calls the HTTP API from your browser, so keep that address as it is. OpenFGA runs without authentication (`OPENFGA_AUTHN_METHOD: none`). The database is reachable inside Docker only.

## Logins and secrets

| What | Value | Setting |
|---|---|---|
| Password of the database user `openfga`, inside Docker only | `openfga`, a public demo value | `OPENFGA_POSTGRES_PASSWORD` |

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `OPENFGA_VERSION` | `v1.22.0` | OpenFGA version (image tag) |
| `OPENFGA_POSTGRES_VERSION` | `17.11` | PostgreSQL version (image tag) |
| `OPENFGA_POSTGRES_PASSWORD` | `openfga` | Password of the database user `openfga`. The database keeps the password it was first created with: set it before the first start, or remove the add-on's data volume, which deletes the stores and models ([how](https://github.com/gravitee-io-labs/gravitee-lab/blob/main/docs/configuration.md#data-and-volumes)) |

## What stays after removal

The stores and models live in the Docker volume `data-openfga`. Stopping the add-on keeps them, and `make reset` deletes them. `gio-openfga-migrate` creates the schema, then exits: it shows as **Done**.
