"""Store verification adapters (spec §31.4, §31.5).

Google: Play Developer API product purchase lookup + acknowledge (service-account credentials).
Apple: StoreKit 2 / App Store Server Notifications V2 JWS, verified against the x5c chain up to a pinned
Apple root certificate. Fake adapters exist for local/emulator use only (settings forbid them in stage/prod).
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import anyio
import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes

from app.common.errors import ApiError, ErrorCode

PLAY_API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"
PLAY_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
# Apple Root CA - G3, pinned for App Store signed transactions (public, from apple.com/certificateauthority).
BUNDLED_APPLE_ROOT = str(Path(__file__).parent / "certs" / "AppleRootCA-G3.cer")

_PURCHASE_STATES = {0: "PURCHASED", 1: "CANCELLED", 2: "PENDING"}


@dataclass(frozen=True)
class GooglePurchase:
    state: str  # PURCHASED | CANCELLED | PENDING
    order_id: str | None
    acknowledged: bool
    purchase_time_ms: int
    account_hash: str | None = None


class GooglePlayClient(Protocol):
    async def get(self, product_id: str, token: str) -> GooglePurchase: ...

    async def acknowledge(self, product_id: str, token: str) -> None: ...


class GooglePlayApiClient:
    def __init__(self, package: str, limiter: anyio.CapacityLimiter) -> None:
        self._package = package
        self._limiter = limiter

    async def _token(self) -> str:
        import google.auth
        import google.auth.transport.requests

        def refresh() -> str:
            credentials, _ = google.auth.default(scopes=[PLAY_SCOPE])
            credentials.refresh(google.auth.transport.requests.Request())
            return credentials.token

        return await anyio.to_thread.run_sync(refresh, limiter=self._limiter)

    def _url(self, product_id: str, token: str) -> str:
        return f"{PLAY_API}/{self._package}/purchases/products/{product_id}/tokens/{token}"

    async def get(self, product_id: str, token: str) -> GooglePurchase:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(self._url(product_id, token),
                                   headers={"authorization": f"Bearer {await self._token()}"})
        if res.status_code in (400, 404, 410):
            raise ApiError(ErrorCode.PURCHASE_NOT_VERIFIED, detail={"reason": "unknown_token"})
        res.raise_for_status()
        data = res.json()
        return GooglePurchase(state=_PURCHASE_STATES.get(int(data.get("purchaseState", 1)), "CANCELLED"),
                              order_id=data.get("orderId"), acknowledged=int(data.get("acknowledgementState", 0)) == 1,
                              purchase_time_ms=int(data.get("purchaseTimeMillis", 0)),
                              account_hash=data.get("obfuscatedExternalAccountId"))

    async def acknowledge(self, product_id: str, token: str) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(self._url(product_id, token) + ":acknowledge",
                                    headers={"authorization": f"Bearer {await self._token()}"}, json={})
        if res.status_code not in (200, 204, 400):  # 400: already acknowledged
            res.raise_for_status()


class FakeGooglePlay:
    """Deterministic in-memory Play API for dev/tests."""

    def __init__(self) -> None:
        self.purchases: dict[str, GooglePurchase] = {}
        self.acknowledged: list[str] = []

    async def get(self, product_id: str, token: str) -> GooglePurchase:
        if token not in self.purchases:
            raise ApiError(ErrorCode.PURCHASE_NOT_VERIFIED, detail={"reason": "unknown_token"})
        return self.purchases[token]

    async def acknowledge(self, product_id: str, token: str) -> None:
        self.acknowledged.append(token)
        purchase = self.purchases[token]
        self.purchases[token] = GooglePurchase(purchase.state, purchase.order_id, True, purchase.purchase_time_ms,
                                               purchase.account_hash)


# ---------------------------------------------------------------------------------------------- Apple


class AppleVerifier(Protocol):
    def decode(self, signed: str) -> dict[str, Any]: ...


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4))


class AppleJwsVerifier:
    """Verifies ES256 JWS whose x5c chain ends in a pinned Apple root (fingerprint match)."""

    def __init__(self, root_certificates: list[x509.Certificate], now=None) -> None:
        if not root_certificates:
            raise ValueError("at least one pinned Apple root certificate is required")
        self._roots = {c.fingerprint(hashes.SHA256()) for c in root_certificates}
        self._now = now or (lambda: dt.datetime.now(dt.UTC))

    @classmethod
    def from_paths(cls, paths: list[str]) -> AppleJwsVerifier:
        certs = []
        for path in paths:
            with open(path, "rb") as fh:
                raw = fh.read()
            certs.append(x509.load_pem_x509_certificate(raw) if b"BEGIN CERT" in raw
                         else x509.load_der_x509_certificate(raw))
        return cls(certs)

    def decode(self, signed: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(signed)
            chain = [x509.load_der_x509_certificate(_b64decode(c)) for c in header.get("x5c") or []]
            if header.get("alg") != "ES256" or len(chain) < 2:
                raise ValueError("unexpected header")
            now = self._now()
            for cert, issuer in zip(chain, chain[1:], strict=False):
                cert.verify_directly_issued_by(issuer)
            for cert in chain:
                if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
                    raise ValueError("certificate outside validity")
            if chain[-1].fingerprint(hashes.SHA256()) not in self._roots:
                raise ValueError("untrusted root")
            return jwt.decode(signed, key=chain[0].public_key(), algorithms=["ES256"],
                              options={"verify_aud": False, "verify_exp": False})
        except Exception as exc:  # noqa: BLE001 - chain, signature and JWS errors all mean "not verified"
            raise ApiError(ErrorCode.PURCHASE_NOT_VERIFIED, detail={"reason": "apple_signature"}) from exc


class FakeAppleVerifier:
    """Dev/test only: HS256 JWS with the internal dev secret."""

    def __init__(self, secret: str) -> None:
        import hashlib

        self._secret = hashlib.sha256(f"apple-dev:{secret}".encode()).hexdigest()

    def encode(self, payload: dict[str, Any]) -> str:
        return jwt.encode(payload, self._secret, algorithm="HS256")

    def decode(self, signed: str) -> dict[str, Any]:
        try:
            return jwt.decode(signed, self._secret, algorithms=["HS256"], options={"verify_aud": False})
        except jwt.PyJWTError as exc:
            raise ApiError(ErrorCode.PURCHASE_NOT_VERIFIED, detail={"reason": "apple_signature"}) from exc


class AppleStoreClient(Protocol):
    async def transaction_info(self, transaction_id: str) -> str | None:
        """Latest signed transaction (JWS) for ``transaction_id``; None when Apple has no record."""
        ...


class AppStoreServerApiClient:
    """App Store Server API (``GET /inApps/v1/transactions/{id}``) authenticated with an ES256 JWT."""

    HOSTS = {"Production": "https://api.storekit.itunes.apple.com",
             "Sandbox": "https://api.storekit-sandbox.itunes.apple.com"}

    def __init__(self, *, issuer_id: str, key_id: str, private_key_pem: str, bundle_id: str,
                 environment: str = "Production", clock=None) -> None:
        if not (issuer_id and key_id and private_key_pem):
            raise ValueError("App Store Server API credentials are required")
        self._issuer, self._key_id, self._key, self._bundle = issuer_id, key_id, private_key_pem, bundle_id
        self._host = self.HOSTS[environment]
        self._clock = clock or (lambda: int(dt.datetime.now(dt.UTC).timestamp()))

    def token(self) -> str:
        now = self._clock()
        return jwt.encode({"iss": self._issuer, "iat": now, "exp": now + 1200, "aud": "appstoreconnect-v1",
                           "bid": self._bundle}, self._key, algorithm="ES256",
                          headers={"kid": self._key_id, "typ": "JWT"})

    async def transaction_info(self, transaction_id: str) -> str | None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{self._host}/inApps/v1/transactions/{transaction_id}",
                                   headers={"authorization": f"Bearer {self.token()}"})
        if res.status_code == 404:
            return None
        res.raise_for_status()
        return res.json().get("signedTransactionInfo")


class FakeAppleStore:
    """Dev/test: latest signed transaction per original transaction ID."""

    def __init__(self) -> None:
        self.transactions: dict[str, str] = {}

    async def transaction_info(self, transaction_id: str) -> str | None:
        return self.transactions.get(transaction_id)


def decode_pubsub_data(envelope: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(base64.b64decode(envelope["message"]["data"]).decode())
    except (KeyError, ValueError, TypeError) as exc:
        raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "pubsub_envelope"}) from exc
