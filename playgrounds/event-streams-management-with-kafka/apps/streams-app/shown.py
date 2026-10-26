"""How much of a record the page is sent: a large order has a 120 KB invoice that nobody reads on a screen."""
import json

LIMIT = 1200            # characters of a value the page is sent
LONG = 80               # a string field longer than this is cut to its start


def cut(value):
    if isinstance(value, str) and len(value) > LONG:
        return f"{value[:32]}… ({len(value)} chars)"
    if isinstance(value, dict):
        return {k: cut(v) for k, v in value.items()}
    if isinstance(value, list):
        return [cut(v) for v in value]
    return value


def shorten(text: str, limit: int = LIMIT) -> str:
    """The text as it is when it is short; a JSON document with its long strings cut to their start; else its first characters."""
    if len(text) <= limit:
        return text
    try:
        parsed = json.loads(text)
    except ValueError:
        return text[:limit] + "…"
    short = json.dumps(cut(parsed), ensure_ascii=False)
    return short if len(short) <= limit else short[:limit] + "…"
