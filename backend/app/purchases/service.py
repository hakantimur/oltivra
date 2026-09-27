"""Remove Ads Forever: server-verified entitlement lifecycle (spec §18.11, §31.3–31.5).

PENDING grants nothing. Transactions are recorded idempotently and bound to the first verified UID
(restore works for that UID after login). Refund, revocation, family-share revocation and reactivation
arrive through verified store notifications and scheduled reconciliation.
"""

from __future__ import annotations

import logging
from typing import Any

from app.common.errors import ApiError, ErrorCode
from app.common.ids import sha256_hex
from app.common.store.docstore import Query
from app.purchases.verifiers import AppleVerifier, GooglePlayClient, decode_pubsub_data

log = logging.getLogger("oltivra.purchases")

PRODUCT_ID = "remove_ads_forever"
APPLE_REVOKE_TYPES = {"REFUND", "REVOKE"}
APPLE_RESTORE_TYPES = {"REFUND_REVERSED"}


def entitlement_path(uid: str) -> str:
    return f"purchase_entitlements/{uid}"


def google_tx_path(token: str) -> str:
    return f"purchase_transactions/g_{sha256_hex(token)[:40]}"


def apple_tx_path(original_transaction_id: str) -> str:
    return f"purchase_transactions/a_{original_transaction_id}"


class PurchaseService:
    def __init__(self, container, google: GooglePlayClient, apple: AppleVerifier) -> None:
        self._c = container
        self.google = google
        self.apple = apple

    # ------------------------------------------------------------------------------------------ core
    async def _record(self, uid: str | None, tx_path: str, tx: dict[str, Any], active: bool | None) -> dict[str, Any]:
        """Bind/update a transaction and derive the entitlement. ``active`` None = leave entitlement alone."""
        now = self._c.clock.now_ms()
        tx_id = tx_path.split("/")[1]

        def txn_fn(txn) -> dict[str, Any]:
            existing = txn.get(tx_path)
            owner = (existing or {}).get("uid") or uid
            if existing and uid and existing.get("uid") and existing["uid"] != uid:
                raise ApiError(ErrorCode.CONFLICT, detail={"reason": "purchase_bound_to_other_account"})
            if not owner:
                return {"state": "UNKNOWN_TRANSACTION"}
            entitlement = txn.get(entitlement_path(owner))
            txn.set(tx_path, {**(existing or {}), **tx, "schema_version": 1, "uid": owner, "updated_at_ms": now,
                              "created_at_ms": (existing or {}).get("created_at_ms", now)})
            if active is True:
                txn.set(entitlement_path(owner), {
                    "schema_version": 1, "uid": owner, "remove_ads": True, "source_store": tx["store"],
                    "latest_verified_transaction_id": tx_id, "state": "ACTIVE", "updated_at_ms": now})
            elif active is False and entitlement and entitlement.get("latest_verified_transaction_id") == tx_id:
                txn.set(entitlement_path(owner), {**entitlement, "remove_ads": False, "state": "REVOKED",
                                                  "updated_at_ms": now})
            return {"state": tx["state"], "uid": owner}

        from app.moderation.risk import RiskSignal, watch

        async with watch(self._c, uid, RiskSignal.PURCHASE_ANOMALY, reasons={"purchase_bound_to_other_account"},
                         evidence={"tx": tx_id}):
            return await self._c.store.run_transaction(txn_fn)

    async def entitlements(self, uid: str) -> dict[str, Any]:
        doc = await self._c.store.get(entitlement_path(uid)) or {}
        return {"schema_version": 1, "remove_ads": bool(doc.get("remove_ads") and doc.get("state") == "ACTIVE"),
                "state": doc.get("state", "NONE"), "source_store": doc.get("source_store"),
                "products": [{"product_id": PRODUCT_ID, "type": "NON_CONSUMABLE",
                              "owned": bool(doc.get("remove_ads") and doc.get("state") == "ACTIVE")}]}

    # ------------------------------------------------------------------------------------------ Google
    async def verify_google(self, uid: str, product_id: str, token: str) -> dict[str, Any]:
        if product_id != PRODUCT_ID:
            raise ApiError(ErrorCode.PURCHASE_NOT_VERIFIED, detail={"reason": "unknown_product"})
        purchase = await self.google.get(product_id, token)
        tx = {"store": "GOOGLE_PLAY", "product_id": product_id, "order_id": purchase.order_id,
              "token_hash": sha256_hex(token), "purchase_token": token, "state": purchase.state,
              "purchase_time_ms": purchase.purchase_time_ms}
        outcome = await self._record(uid, google_tx_path(token), tx,
                                     True if purchase.state == "PURCHASED" else
                                     (False if purchase.state == "CANCELLED" else None))
        if purchase.state == "PURCHASED" and not purchase.acknowledged:
            await self.google.acknowledge(product_id, token)  # Play refunds unacknowledged purchases after 3 days
        return {**await self.entitlements(uid), "purchase_state": outcome["state"]}

    async def handle_google_rtdn(self, envelope: dict[str, Any]) -> dict[str, Any]:
        data = decode_pubsub_data(envelope)
        if data.get("packageName") and data["packageName"] != self._c.settings.google_play_package:
            return {"ignored": "package"}
        voided = data.get("voidedPurchaseNotification")
        one_time = data.get("oneTimeProductNotification")
        if data.get("testNotification"):
            return {"ignored": "test"}
        token = (voided or one_time or {}).get("purchaseToken")
        if not token:
            return {"ignored": "no_token"}
        existing = await self._c.store.get(google_tx_path(token))
        if voided:
            if not existing:
                return {"ignored": "unknown_transaction"}
            tx = {**existing, "state": "REVOKED", "voided_refund_type": voided.get("refundType")}
            return await self._record(None, google_tx_path(token), tx, False)
        # Always fetch the current purchase state before changing entitlement (spec §31.4).
        product = (one_time or {}).get("sku") or PRODUCT_ID
        purchase = await self.google.get(product, token)
        if not existing:
            return {"ignored": "unknown_transaction", "state": purchase.state}
        tx = {**existing, "state": purchase.state, "order_id": purchase.order_id}
        active = True if purchase.state == "PURCHASED" else (False if purchase.state == "CANCELLED" else None)
        return await self._record(None, google_tx_path(token), tx, active)

    # ------------------------------------------------------------------------------------------ Apple
    def _apple_tx(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("bundleId") != self._c.settings.apple_bundle_id:
            raise ApiError(ErrorCode.PURCHASE_NOT_VERIFIED, detail={"reason": "bundle"})
        if payload.get("productId") != PRODUCT_ID:
            raise ApiError(ErrorCode.PURCHASE_NOT_VERIFIED, detail={"reason": "unknown_product"})
        revoked = bool(payload.get("revocationDate"))
        return {"store": "APP_STORE", "product_id": PRODUCT_ID, "transaction_id": str(payload.get("transactionId")),
                "original_transaction_id": str(payload.get("originalTransactionId")),
                "ownership": payload.get("inAppOwnershipType", "PURCHASED"),
                "environment": payload.get("environment"), "state": "REVOKED" if revoked else "PURCHASED"}

    async def verify_apple(self, uid: str, signed_transaction: str) -> dict[str, Any]:
        tx = self._apple_tx(self.apple.decode(signed_transaction))
        outcome = await self._record(uid, apple_tx_path(tx["original_transaction_id"]), tx,
                                     tx["state"] == "PURCHASED")
        return {**await self.entitlements(uid), "purchase_state": outcome["state"]}

    async def handle_apple_notification(self, body: dict[str, Any]) -> dict[str, Any]:
        payload = self.apple.decode(body.get("signedPayload", ""))
        kind = payload.get("notificationType")
        data = payload.get("data") or {}
        if data.get("bundleId") and data["bundleId"] != self._c.settings.apple_bundle_id:
            return {"ignored": "bundle"}
        signed_tx = data.get("signedTransactionInfo")
        if not signed_tx:
            return {"ignored": "no_transaction", "type": kind}
        tx = self._apple_tx(self.apple.decode(signed_tx))
        path = apple_tx_path(tx["original_transaction_id"])
        if not await self._c.store.get(path):
            return {"ignored": "unknown_transaction", "type": kind}
        if kind in APPLE_REVOKE_TYPES:
            tx["state"] = "REVOKED"
            return await self._record(None, path, tx, False)
        if kind in APPLE_RESTORE_TYPES or tx["state"] == "PURCHASED":
            return await self._record(None, path, tx, tx["state"] == "PURCHASED")
        return await self._record(None, path, tx, None)

    # ------------------------------------------------------------------------------------------ reconciliation
    async def reconcile_google(self, limit: int = 200) -> int:
        """Scheduled recovery for missed RTDN (spec §31.4)."""
        rows = await self._c.store.query(Query("purchase_transactions").filter("store", "==", "GOOGLE_PLAY")
                                         .filter("state", "in", ["PURCHASED", "PENDING"]).take(limit))
        changed = 0
        for row in rows:
            token = row.data.get("purchase_token")
            if not token:
                continue
            try:
                purchase = await self.google.get(row.data["product_id"], token)
            except ApiError:
                continue
            if purchase.state != row.data["state"]:
                active = True if purchase.state == "PURCHASED" else (False if purchase.state == "CANCELLED" else None)
                await self._record(None, row.path, {**row.data, "state": purchase.state}, active)
                changed += 1
        return changed
