"""Versioned HMAC keyring (spec §28.5: keys carry an explicit key ID/version)."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass


@dataclass(frozen=True)
class KeyVersion:
    key_id: str
    secret: bytes


class HmacKey:
    """One logical key with rotation support; the first version signs, all versions verify."""

    def __init__(self, spec: str) -> None:
        versions: list[KeyVersion] = []
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            key_id, _, secret = part.partition(":")
            if not secret:
                raise ValueError("HMAC key spec entries must be '<id>:<secret>'")
            versions.append(KeyVersion(key_id, secret.encode()))
        if not versions:
            raise ValueError("HMAC key spec is empty")
        self.versions = versions

    @property
    def current(self) -> KeyVersion:
        return self.versions[0]

    def digest(self, message: str, key_id: str | None = None) -> bytes:
        version = self.current if key_id is None else self._by_id(key_id)
        return hmac.new(version.secret, message.encode(), hashlib.sha256).digest()

    def hexdigest(self, message: str, key_id: str | None = None) -> str:
        return self.digest(message, key_id).hex()

    def first_uint32(self, message: str) -> int:
        return int.from_bytes(self.digest(message)[:4], "big")

    def verify(self, message: str, signature_hex: str, key_id: str) -> bool:
        try:
            expected = self.hexdigest(message, key_id)
        except KeyError:
            return False
        return hmac.compare_digest(expected, signature_hex)

    def _by_id(self, key_id: str) -> KeyVersion:
        for version in self.versions:
            if version.key_id == key_id:
                return version
        raise KeyError(key_id)


@dataclass(frozen=True)
class Keyring:
    tiebreak: HmacKey
    resolver: HmacKey
    shard: HmacKey
    bot_plan: HmacKey
    reward: HmacKey
    mission: HmacKey
    username_hash: HmacKey

    @classmethod
    def from_settings(cls, settings) -> Keyring:
        return cls(
            tiebreak=HmacKey(settings.tiebreak_keys),
            resolver=HmacKey(settings.resolver_keys),
            shard=HmacKey(settings.shard_keys),
            bot_plan=HmacKey(settings.bot_plan_keys),
            reward=HmacKey(settings.reward_keys),
            mission=HmacKey(settings.mission_keys),
            username_hash=HmacKey(settings.username_hash_keys),
        )
