# RedisInsight

[RedisInsight](https://redis.io/insight/) is a graphical client for Redis. It opens already connected to the lab's Redis, under the name Gravitee. That Redis holds the gateway's rate limit counters, caches and vector stores.

## Needs

Nothing more than the platform.

## Ports

| Port | What it is | Login |
|---|---|---|
| 5540 | RedisInsight, http://localhost:5540 | None |

It listens on `127.0.0.1` only.

## Logins and secrets

| What | Value | Setting |
|---|---|---|
| Password of the lab's Redis, which the connection is made with | `redispassword`, a public demo value, the core's | `REDIS_PASSWORD` |

RedisInsight itself needs no sign-in.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `REDISINSIGHT_VERSION` | `3.8.0` | RedisInsight version (image tag), chosen on the Images page |

## What stays after removal

What you save in RedisInsight, such as other connections, lives in the Docker volume `data-redisinsight`. Stopping the add-on keeps it, and `make reset` deletes it. The Redis data itself is the core's.
