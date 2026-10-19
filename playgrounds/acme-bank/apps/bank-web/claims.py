"""Claims of an access token, read without checking the signature: for display only (the gateway and AM verify)."""
import base64
import json
from typing import Any


def jwt_claims(token: str) -> dict[str, Any]:
    try:
        body = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (IndexError, ValueError):
        return {}
    return claims if isinstance(claims, dict) else {}
