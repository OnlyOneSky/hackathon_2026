"""Webhook signature verification (infra doc §1 rule: raw body, compare_digest)."""
from __future__ import annotations

import hashlib
import hmac


def verify_signature(raw_body: bytes, secret: str, signature: str) -> bool:
    """Taiga signs webhooks with HMAC-SHA1 hex over the raw request body."""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha1).hexdigest()
    return hmac.compare_digest(expected, signature)
