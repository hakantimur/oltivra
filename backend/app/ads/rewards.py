"""Rewarded XP offers and AdMob server-side verification (spec §7.2, §31.2).

The client reward callback never grants XP. The backend creates a one-time 15-minute offer with signed
compact custom data; only a provider-signed SSV callback whose offer, expiry, nonce, UID and match binding
all check out grants exactly one extra copy of the match's base XP — once, idempotently, within the daily
cap. Reward XP never touches ranked weekly XP, MMR, missions or anything competitive.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, Protocol
from urllib.parse import parse_qsl

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.common.clock import ms_to_datetime, utc_date_id
from app.common.errors import ApiError, ErrorCode
from app.common.ids import random_token
from app.profiles.service import user_path
from app.ranking.levels import level_for_xp

log = logging.getLogger("oltivra.rewards")

ADMOB_KEYS_URL = "https://www.gstatic.com/admob/reward/verifier-keys.json"
KEY_CACHE_S = 24 * 3600


# ---------------------------------------------------------------------------------------------- SSV verification


class SsvVerifier(Protocol):
    async def verify(self, raw_query: str) -> dict[str, str]: ...


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def split_signed_query(raw_query: str) -> tuple[str, str, str]:
    """AdMob signs the query string up to (not including) ``&signature=``; signature and key_id are last."""
    marker = "&signature="
    index = raw_query.find(marker)
    if index < 0:
        raise ApiError(ErrorCode.REWARD_NOT_VERIFIED, detail={"reason": "unsigned"})
    message = raw_query[:index]
    tail = dict(parse_qsl(raw_query[index + 1:], keep_blank_values=True))
    if "signature" not in tail or "key_id" not in tail:
        raise ApiError(ErrorCode.REWARD_NOT_VERIFIED, detail={"reason": "malformed_signature"})
    return message, tail["signature"], tail["key_id"]


class AdMobSsvVerifier:
    """ECDSA P-256/SHA-256 over the signed query, keys from Google's published verifier key set."""

    def __init__(self, key_provider=None) -> None:
        self._key_provider = key_provider
        self._keys: dict[str, ec.EllipticCurvePublicKey] = {}
        self._fetched_at = 0.0

    async def _load_keys(self, refresh: bool = False) -> dict[str, ec.EllipticCurvePublicKey]:
        if self._key_provider is not None:
            return self._key_provider()
        if self._keys and not refresh and time.monotonic() - self._fetched_at < KEY_CACHE_S:
            return self._keys
        async with httpx.AsyncClient(timeout=5.0) as client:
            data = (await client.get(ADMOB_KEYS_URL)).json()
        self._keys = {str(k["keyId"]): serialization.load_pem_public_key(k["pem"].encode()) for k in data["keys"]}
        self._fetched_at = time.monotonic()
        return self._keys

    async def verify(self, raw_query: str) -> dict[str, str]:
        message, signature, key_id = split_signed_query(raw_query)
        keys = await self._load_keys()
        if key_id not in keys:
            keys = await self._load_keys(refresh=True)  # key rotation
        key = keys.get(key_id)
        if key is None:
            raise ApiError(ErrorCode.REWARD_NOT_VERIFIED, detail={"reason": "unknown_key"})
        try:
            key.verify(_b64url_decode(signature), message.encode(), ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, ValueError) as exc:
            raise ApiError(ErrorCode.REWARD_NOT_VERIFIED, detail={"reason": "bad_signature"}) from exc
        return dict(parse_qsl(message, keep_blank_values=True))


class DevSsvVerifier:
    """Local/emulator only (forbidden in stage/prod by settings guards): HMAC-SHA256 with the dev secret."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()

    def sign(self, message: str) -> str:
        import hashlib
        import hmac

        return hmac.new(self._secret, message.encode(), hashlib.sha256).hexdigest()

    async def verify(self, raw_query: str) -> dict[str, str]:
        import hmac

        message, signature, _ = split_signed_query(raw_query)
        if not hmac.compare_digest(self.sign(message), signature):
            raise ApiError(ErrorCode.REWARD_NOT_VERIFIED, detail={"reason": "bad_signature"})
        return dict(parse_qsl(message, keep_blank_values=True))


# ---------------------------------------------------------------------------------------------- offers


def offer_path(match_id: str, uid: str) -> str:
    return f"reward_offers/{match_id}_{uid}"


class RewardService:
    def __init__(self, container, verifier: SsvVerifier) -> None:
        self._c = container
        self.verifier = verifier

    def uid_hash(self, uid: str) -> str:
        return self._c.keys.reward.hexdigest(f"uid:{uid}")[:24]

    def _sign(self, body: str) -> str:
        return self._c.keys.reward.hexdigest(f"offer:{body}")[:32]

    def custom_data(self, offer: dict[str, Any]) -> str:
        body = ".".join(["v1", offer["offer_id"], self.uid_hash(offer["uid"]), offer["match_id"],
                         str(offer["offer_expires_at_ms"]), offer["nonce"]])
        return f"{body}.{self._sign(body)}"

    def parse_custom_data(self, value: str) -> dict[str, Any]:
        parts = value.split(".")
        if len(parts) != 7 or parts[0] != "v1":
            raise ApiError(ErrorCode.REWARD_NOT_VERIFIED, detail={"reason": "custom_data"})
        body, signature = ".".join(parts[:6]), parts[6]
        if self._sign(body) != signature:
            raise ApiError(ErrorCode.REWARD_NOT_VERIFIED, detail={"reason": "custom_data_signature"})
        return {"offer_id": parts[1], "uid_hash": parts[2], "match_id": parts[3], "expires_at_ms": int(parts[4]),
                "nonce": parts[5]}

    def _view(self, offer: dict[str, Any]) -> dict[str, Any]:
        view = {"schema_version": 1, "match_id": offer["match_id"], "state": offer["state"],
                "base_xp": offer.get("base_xp", 0), "bonus_xp": offer.get("base_xp", 0)}
        if offer["state"] == "OFFERED":
            view.update(offer_id=offer["offer_id"], custom_data=self.custom_data(offer),
                        ssv_user_id=self.uid_hash(offer["uid"]), expires_at_ms=offer["offer_expires_at_ms"])
        return view

    async def status(self, uid: str, match_id: str) -> dict[str, Any]:
        offer = await self._c.store.get(offer_path(match_id, uid))
        if not offer:
            raise ApiError(ErrorCode.NOT_FOUND)
        return self._view(offer)

    async def start(self, uid: str, match_id: str) -> dict[str, Any]:
        """Verify settled match, UID, daily cap and no existing grant; create the one-time offer."""
        c = self._c
        config = await c.config.get()
        if not config.features.rewarded_offers_enabled:
            raise ApiError(ErrorCode.FEATURE_DISABLED, detail={"feature": "rewarded_xp"})
        now = c.clock.now_ms()
        daily = f"reward_daily/{uid}_{utc_date_id(now)}"

        def txn_fn(txn) -> dict[str, Any]:
            offer, counter, ledger = txn.get_many([offer_path(match_id, uid), daily,
                                                   f"settlement_ledgers/{match_id}"])
            if not offer or not ledger or ledger.get("status") != "SETTLED":
                raise ApiError(ErrorCode.NOT_FOUND, detail={"reason": "no_reward_offer"})
            if offer["state"] == "GRANTED":
                return offer
            if int((counter or {}).get("grants", 0)) >= config.economy.rewarded_xp_daily_cap:
                raise ApiError(ErrorCode.REWARD_CAP_REACHED)
            if offer["state"] == "OFFERED" and offer["offer_expires_at_ms"] > now:
                return offer  # one live offer per settled match
            eligible_until = int(offer.get("eligible_until_ms") or offer["created_at_ms"] +
                                 config.economy.reward_offer_ttl_ms)
            if now >= eligible_until:
                # The offer window is fixed at settlement; an expired offer cannot be restarted forever.
                raise ApiError(ErrorCode.NOT_FOUND, detail={"reason": "reward_offer_expired"})
            expires = min(now + config.economy.reward_offer_ttl_ms, eligible_until + config.economy.reward_offer_ttl_ms)
            updated = {**offer, "state": "OFFERED", "offer_id": random_token(12).replace(".", "_"),
                       "nonce": random_token(12).replace(".", "_"), "offered_at_ms": now,
                       "offer_expires_at_ms": expires, "expires_at": ms_to_datetime(expires + 86_400_000)}
            txn.set(offer_path(match_id, uid), updated)
            return updated

        return self._view(await c.store.run_transaction(txn_fn))

    async def handle_ssv(self, raw_query: str) -> dict[str, Any]:
        """Internal AdMob SSV endpoint. Duplicate/malformed/late callbacks are safe no-ops or errors."""
        c = self._c
        params = await self.verifier.verify(raw_query)
        data = self.parse_custom_data(params.get("custom_data", ""))
        if params.get("user_id") and params["user_id"] != data["uid_hash"]:
            raise ApiError(ErrorCode.REWARD_NOT_VERIFIED, detail={"reason": "user_binding"})
        transaction_id = params.get("transaction_id")
        if not transaction_id:
            raise ApiError(ErrorCode.REWARD_NOT_VERIFIED, detail={"reason": "transaction_id"})
        config = await c.config.get()
        now = c.clock.now_ms()
        if now > data["expires_at_ms"]:
            raise ApiError(ErrorCode.REWARD_NOT_VERIFIED, detail={"reason": "offer_expired"})
        match_id = data["match_id"]

        def txn_fn(txn) -> dict[str, Any]:
            existing_tx = txn.get(f"reward_transactions/{transaction_id}")
            rows = [r for r in txn.query(_offer_query(match_id, data["offer_id"]))]
            offer = rows[0].data if rows else None
            uid = offer["uid"] if offer else None
            user, counter = txn.get_many([user_path(uid), f"reward_daily/{uid}_{utc_date_id(now)}"]) if uid \
                else (None, None)
            if existing_tx:
                return {"granted": False, "duplicate": True}
            if not offer or offer.get("state") != "OFFERED" or offer.get("nonce") != data["nonce"] \
                    or self.uid_hash(uid) != data["uid_hash"] or offer.get("offer_expires_at_ms", 0) < now:
                raise ApiError(ErrorCode.REWARD_NOT_VERIFIED, detail={"reason": "offer_state"})
            if not user:
                raise ApiError(ErrorCode.REWARD_NOT_VERIFIED, detail={"reason": "user"})
            grants = int((counter or {}).get("grants", 0))
            if grants >= config.economy.rewarded_xp_daily_cap:
                raise ApiError(ErrorCode.REWARD_CAP_REACHED)
            bonus = int(offer.get("base_xp", 0))
            total = int(user.get("total_xp", 0)) + bonus
            sequence = int(user.get("progression_sequence", 0)) + 1
            txn.create(f"reward_transactions/{transaction_id}", {
                "schema_version": 1, "transaction_id": transaction_id, "uid": uid, "match_id": match_id,
                "offer_id": offer["offer_id"], "ad_unit": params.get("ad_unit"), "at_ms": now})
            txn.update(offer_path(match_id, uid), {"state": "GRANTED", "granted_at_ms": now,
                                                   "transaction_id": transaction_id})
            txn.set(f"reward_daily/{uid}_{utc_date_id(now)}", {"uid": uid, "grants": grants + 1,
                                                               "updated_at_ms": now})
            # Lifetime XP only: ranked weekly XP, MMR, missions and badges are untouched (spec §7.2).
            txn.update(user_path(uid), {"total_xp": total, "progression_sequence": sequence})
            txn.set(f"public_profiles/{user['public_id']}", c.profiles.public_profile({**user, "total_xp": total}))
            txn.set(f"progression_events/{uid}_{sequence:08d}", {
                "schema_version": 1, "uid": uid, "sequence": sequence, "match_id": match_id,
                "kind": "REWARD_BONUS", "xp": bonus, "at_ms": now})
            return {"granted": True, "duplicate": False, "uid": uid, "bonus_xp": bonus, "total_xp": total,
                    "level": level_for_xp(total)}

        try:
            result = await c.store.run_transaction(txn_fn)
        except ApiError as exc:
            if (exc.detail or {}).get("reason") == "offer_state":
                # A signed callback that does not match the offer binding is a reward anomaly (spec §28.4).
                from app.moderation.risk import RiskSignal

                rows = await c.store.query(_offer_query(match_id, data["offer_id"]))
                if rows and rows[0].data.get("uid"):
                    await c.risk.record(rows[0].data["uid"], RiskSignal.REWARD_ANOMALY,
                                        evidence={"match_id": match_id})
            raise
        return {"ok": True, "granted": result["granted"], "duplicate": result["duplicate"]}


def _offer_query(match_id: str, offer_id: str):
    from app.common.store.docstore import Query

    return Query("reward_offers").filter("match_id", "==", match_id).filter("offer_id", "==", offer_id).take(1)
