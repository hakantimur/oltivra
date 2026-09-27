from __future__ import annotations

import hashlib
import secrets
import uuid


def new_uuid() -> str:
    return str(uuid.uuid4())


def is_uuid4(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.version == 4 and str(parsed) == value.lower()


def random_token(nbytes: int = 24) -> str:
    """Cryptographically random URL-safe token (party IDs, invite tokens, nonces)."""
    return secrets.token_urlsafe(nbytes)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def ordered_pair_id(uid_a: str, uid_b: str) -> str:
    first, second = sorted((uid_a, uid_b))
    return f"{first}_{second}"
