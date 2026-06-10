"""Incoming-webhook authentication via HMAC-SHA256.

This mirrors how providers like Stripe, GitHub, and Shopify sign their webhooks:
the sender HMACs the raw request body with a shared secret and sends the hex
digest in a header. We recompute it and compare in constant time.
"""
from __future__ import annotations

import hashlib
import hmac

SIGNATURE_HEADER = "x-hookrelay-signature"


def sign(secret: str, body: bytes) -> str:
    """Produce the hex signature for a body. Useful for senders and for tests."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, provided_signature: str | None) -> bool:
    """Return True iff the provided signature matches.

    Uses compare_digest to avoid leaking timing information about how many
    leading bytes matched.
    """
    if not provided_signature:
        return False
    expected = sign(secret, body)
    return hmac.compare_digest(expected, provided_signature.strip())
