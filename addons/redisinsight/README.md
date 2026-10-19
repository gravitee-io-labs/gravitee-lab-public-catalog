# RedisInsight

[RedisInsight](https://redis.io/insight/) is a graphical client for Redis. It opens already connected to the lab's Redis, under the name Gravitee. That Redis holds the gateway's rate limit counters, caches and vector stores. Open RedisInsight on http://localhost:5540.

The connection is made for you, with the core's Redis password (`REDIS_PASSWORD`, `redispassword` by default). RedisInsight itself needs no sign-in, and its port binds `127.0.0.1`.

## Settings

| Setting | Meaning |
|---|---|
| `REDISINSIGHT_VERSION` | RedisInsight version (image tag), chosen on the Images page |

## What stays after removal

What you save in RedisInsight, such as other connections, lives in the Docker volume `data-redisinsight`. Stopping the add-on keeps it, and `make reset` deletes it. The Redis data itself is the core's.
