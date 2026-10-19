"""Calls to an OpenAI-compatible endpoint of the gateway (the LLM proxy, an AI workspace) and what the page shows of
their answers: the text, the tokens, the limits the gateway reports and whether the semantic cache answered."""
import time
from typing import Any

import httpx

from upstream import GATEWAY_REQUEST, GATEWAY_TRANSACTION, UpstreamError, clean, elapsed_ms, json_body, message_of

CACHE_ANSWER_ID = "resp_llmproxy"        # the id of an answer that came from the semantic cache, not from a model
MODEL = "acme-chat"


def _number(headers: httpx.Headers, name: str) -> int | None:
    try:
        return int(headers[name])
    except (KeyError, ValueError):
        return None


def limits(headers: httpx.Headers, prefix: str) -> dict[str, int | None] | None:
    """The gateway's `<prefix>-Limit`, `-Remaining` and `-Reset` (epoch ms) headers, when it sent them."""
    found = {key: _number(headers, f"{prefix}-{key}") for key in ("limit", "remaining", "reset")}
    return found if any(v is not None for v in found.values()) else None


def _tokens(body: Any, headers: httpx.Headers) -> dict[str, int | None] | None:
    usage = body.get("usage") if isinstance(body, dict) else None
    if isinstance(usage, dict):
        return {"prompt": usage.get("prompt_tokens"), "completion": usage.get("completion_tokens"),
                "total": usage.get("total_tokens")}
    sent, received = _number(headers, "x-llm-proxy-tokens-sent"), _number(headers, "x-llm-proxy-tokens-received")
    return {"prompt": sent, "completion": received, "total": (sent or 0) + (received or 0)} if sent or received else None


def _answer(body: Any) -> str:
    try:
        return body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


async def complete(http: httpx.AsyncClient, url: str, headers: dict[str, str], payload: dict, rate_prefix: str) -> dict:
    """One chat completion, whatever the gateway answers: a 400, a 429 or a 504 is data for the page, not an error."""
    started = time.monotonic()
    try:
        response = await http.post(f"{url.rstrip('/')}/chat/completions", headers=headers, json=payload)
    except httpx.HTTPError as e:
        raise UpstreamError("The gateway is not answering") from e
    body = json_body(response)
    ok = response.status_code == 200
    return {
        "status": response.status_code,
        "ms": elapsed_ms(started),
        "answer": _answer(body) if ok else "",
        "message": "" if ok else message_of(body, f"HTTP {response.status_code}"),
        "model": body.get("model") if ok and isinstance(body, dict) else None,
        "tokens": _tokens(body, response.headers) if ok else None,
        "cached": ok and isinstance(body, dict) and body.get("id") == CACHE_ANSWER_ID,
        "limits": limits(response.headers, rate_prefix),
        "transaction_id": response.headers.get(GATEWAY_TRANSACTION),
        "request_id": clean(response.headers.get(GATEWAY_REQUEST)),
    }


def bearer(key: str) -> dict[str, str]:
    """The LLM proxy's plans read the key from the Authorization header."""
    return {"Authorization": f"Bearer {key}"}


async def ask(http: httpx.AsyncClient, url: str, key: str, content: str, max_tokens: int,
              model: str = MODEL) -> dict:
    """A question to the LLM proxy as a developer, with the Developers key."""
    if not key:
        raise UpstreamError("DEV_LLM_API_KEY is not set", 503)
    payload = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens}
    return await complete(http, url, bearer(key), payload, "x-token-rate-limit")
