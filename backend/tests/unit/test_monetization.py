"""Rewarded XP SSV and Remove Ads purchase lifecycle (spec §31, §40.6 SSV/purchase cases)."""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.ads.rewards import AdMobSsvVerifier
from app.common.clock import iso_week_id
from app.purchases.verifiers import AppleJwsVerifier, GooglePurchase
from tests.unit.test_matchmaking import bot_fill_match, play_round_human_wins

KEY_ID = "3335741209"


@pytest.fixture
def players(api):
    for uid in ("u1", "u2"):
        api.onboard(uid)
    return api


@pytest.fixture
def ssv_key(container):
    private = ec.generate_private_key(ec.SECP256R1())
    container.rewards.verifier = AdMobSsvVerifier(lambda: {KEY_ID: private.public_key()})
    return private


def settled_match(players, container, uid="u1"):
    match_id = bot_fill_match(players, container, uid)
    for _ in range(10):
        play_round_human_wins(players, container, match_id, uid=uid)
    return match_id


def ssv_query(private, offer, transaction_id="tx-1", user_id=None, tamper=None):
    message = (f"ad_network=5450213213286189855&ad_unit=1234567890&custom_data={tamper or offer['custom_data']}"
               f"&reward_amount=1&reward_item=xp&timestamp=1790000000000&transaction_id={transaction_id}"
               f"&user_id={user_id or offer['ssv_user_id']}")
    signature = private.sign(message.encode(), ec.ECDSA(hashes.SHA256()))
    encoded = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{message}&signature={encoded}&key_id={KEY_ID}"


def user(container, uid):
    return container.store._docs[f"users/{uid}"]


# ---------------------------------------------------------------------------------------------- rewards


def test_reward_offer_and_ssv_grant_once(players, container, ssv_key, client):
    match_id = settled_match(players, container)
    offer = players.post(f"/v1/rewards/offers/{match_id}/start", "u1").json()
    assert offer["state"] == "OFFERED" and offer["bonus_xp"] == 200 and offer["custom_data"].startswith("v1.")
    assert players.post(f"/v1/rewards/offers/{match_id}/start", "u1").json()["offer_id"] == offer["offer_id"]
    res = client.get(f"/internal/ads/admob-ssv?{ssv_query(ssv_key, offer)}")
    assert res.status_code == 200 and res.json()["granted"] is True
    assert user(container, "u1")["total_xp"] == 400
    dup = client.get(f"/internal/ads/admob-ssv?{ssv_query(ssv_key, offer)}")
    assert dup.json()["duplicate"] is True and user(container, "u1")["total_xp"] == 400
    replay = client.get(f"/internal/ads/admob-ssv?{ssv_query(ssv_key, offer, transaction_id='tx-2')}")
    assert replay.status_code == 402 and user(container, "u1")["total_xp"] == 400
    assert players.get(f"/v1/rewards/offers/{match_id}", "u1").json()["state"] == "GRANTED"
    # Reward XP never touches ranked weekly XP or MMR.
    week = iso_week_id(container.clock.now_ms())
    assert f"weekly_user_stats/{week}_u1" not in container.store._docs and user(container, "u1")["mmr"] == 1000
    # A granted offer cannot be restarted.
    assert players.post(f"/v1/rewards/offers/{match_id}/start", "u1").json()["state"] == "GRANTED"


def test_ssv_rejects_bad_signature_tampering_and_binding(players, container, ssv_key, client):
    match_id = settled_match(players, container)
    offer = players.post(f"/v1/rewards/offers/{match_id}/start", "u1").json()
    other = ec.generate_private_key(ec.SECP256R1())
    assert client.get(f"/internal/ads/admob-ssv?{ssv_query(other, offer)}").status_code == 402
    tampered = offer["custom_data"][:-3] + "abc"
    assert client.get(f"/internal/ads/admob-ssv?{ssv_query(ssv_key, offer, tamper=tampered)}").status_code == 402
    assert client.get(f"/internal/ads/admob-ssv?{ssv_query(ssv_key, offer, user_id='x' * 24)}").status_code == 402
    unsigned = ssv_query(ssv_key, offer).split("&signature=")[0]
    assert client.get(f"/internal/ads/admob-ssv?{unsigned}").status_code == 402
    assert user(container, "u1")["total_xp"] == 200


def test_ssv_after_offer_expiry_is_rejected(players, container, ssv_key, client):
    match_id = settled_match(players, container)
    offer = players.post(f"/v1/rewards/offers/{match_id}/start", "u1").json()
    container.clock.advance(15 * 60_000 + 1)
    assert client.get(f"/internal/ads/admob-ssv?{ssv_query(ssv_key, offer)}").status_code == 402


def test_reward_offer_window_is_fixed_at_settlement(players, container):
    match_id = settled_match(players, container)
    doc = container.store._docs[f"reward_offers/{match_id}_u1"]
    assert doc["expires_at"] and doc["eligible_until_ms"] - doc["created_at_ms"] == 15 * 60_000
    first = players.post(f"/v1/rewards/offers/{match_id}/start", "u1").json()
    container.clock.advance(14 * 60_000)
    assert players.post(f"/v1/rewards/offers/{match_id}/start", "u1").json()["offer_id"] == first["offer_id"]
    container.clock.advance(2 * 60_000)  # the first offer expired and so did the settlement window
    res = players.post(f"/v1/rewards/offers/{match_id}/start", "u1")
    assert res.status_code == 404 and res.json()["error"]["detail"]["reason"] == "reward_offer_expired"


def test_reward_daily_cap(players, container):
    match_id = settled_match(players, container)
    from app.common.clock import utc_date_id

    container.store._docs[f"reward_daily/u1_{utc_date_id(container.clock.now_ms())}"] = {"grants": 5}
    res = players.post(f"/v1/rewards/offers/{match_id}/start", "u1")
    assert res.status_code == 409 and res.json()["error"]["code"] == "REWARD_CAP_REACHED"


def test_reward_requires_own_settled_match(players, container):
    match_id = bot_fill_match(players, container)
    assert players.post(f"/v1/rewards/offers/{match_id}/start", "u1").status_code == 404
    assert players.post(f"/v1/rewards/offers/{match_id}/start", "u2").status_code == 404


def test_dev_ssv_verifier_path(players, container, client):
    match_id = settled_match(players, container)
    offer = players.post(f"/v1/rewards/offers/{match_id}/start", "u1").json()
    message = (f"ad_unit=1&custom_data={offer['custom_data']}&transaction_id=dev-1&user_id={offer['ssv_user_id']}")
    signed = f"{message}&signature={container.rewards.verifier.sign(message)}&key_id=dev"
    assert client.get(f"/internal/ads/admob-ssv?{signed}").json()["granted"] is True


# ---------------------------------------------------------------------------------------------- Google Play


def test_google_purchase_lifecycle(players, container, client):
    play = container.purchases.google
    play.purchases["tok-purchased-1"] = GooglePurchase("PURCHASED", "GPA.1", False, 1)
    res = players.post("/v1/purchases/verify/google", "u1", {"product_id": "remove_ads_forever",
                                                             "purchase_token": "tok-purchased-1"}).json()
    assert res["remove_ads"] is True and res["purchase_state"] == "PURCHASED"
    assert play.acknowledged == ["tok-purchased-1"]
    assert players.get("/v1/profile", "u1").json()["profile"]["remove_ads"] is True
    # Restore on the same account works; another account cannot claim the purchase.
    again = players.post("/v1/purchases/verify/google", "u1", {"product_id": "remove_ads_forever",
                                                               "purchase_token": "tok-purchased-1"})
    assert again.json()["remove_ads"] is True
    stolen = players.post("/v1/purchases/verify/google", "u2", {"product_id": "remove_ads_forever",
                                                                "purchase_token": "tok-purchased-1"})
    assert stolen.status_code == 409
    # RTDN voided purchase (refund) revokes after verification of the push identity.
    data = base64.b64encode(json.dumps({"packageName": "com.noriloop.oltivra", "voidedPurchaseNotification": {
        "purchaseToken": "tok-purchased-1", "refundType": 1}}).encode()).decode()
    headers = {"x-internal-auth": "dev-internal-secret"}
    res = client.post("/internal/purchases/google-rtdn", json={"message": {"data": data}}, headers=headers)
    assert res.status_code == 200
    assert players.get("/v1/purchases/entitlements", "u1").json()["remove_ads"] is False
    assert client.post("/internal/purchases/google-rtdn", json={"message": {"data": data}}).status_code in (401, 403)


def test_google_pending_grants_nothing_until_purchased(players, container, client):
    play = container.purchases.google
    play.purchases["tok-pending-1"] = GooglePurchase("PENDING", None, False, 1)
    res = players.post("/v1/purchases/verify/google", "u1", {"product_id": "remove_ads_forever",
                                                             "purchase_token": "tok-pending-1"}).json()
    assert res["remove_ads"] is False and res["purchase_state"] == "PENDING"
    play.purchases["tok-pending-1"] = GooglePurchase("PURCHASED", "GPA.2", False, 2)
    data = base64.b64encode(json.dumps({"packageName": "com.noriloop.oltivra", "oneTimeProductNotification": {
        "notificationType": 1, "purchaseToken": "tok-pending-1", "sku": "remove_ads_forever"}}).encode()).decode()
    client.post("/internal/purchases/google-rtdn", json={"message": {"data": data}},
                headers={"x-internal-auth": "dev-internal-secret"})
    assert players.get("/v1/purchases/entitlements", "u1").json()["remove_ads"] is True


def test_google_reconciliation_detects_missed_refund(players, container):
    import asyncio

    play = container.purchases.google
    play.purchases["tok-reconcile-1"] = GooglePurchase("PURCHASED", "GPA.3", True, 1)
    res = players.post("/v1/purchases/verify/google", "u1", {"product_id": "remove_ads_forever",
                                                             "purchase_token": "tok-reconcile-1"})
    assert res.json()["remove_ads"] is True
    play.purchases["tok-reconcile-1"] = GooglePurchase("CANCELLED", "GPA.3", True, 1)
    assert asyncio.run(container.purchases.reconcile_google()) == 1
    assert players.get("/v1/purchases/entitlements", "u1").json()["remove_ads"] is False


def test_unknown_product_rejected(players):
    res = players.post("/v1/purchases/verify/google", "u1", {"product_id": "coins", "purchase_token": "tok-x-123"})
    assert res.status_code == 402


# ---------------------------------------------------------------------------------------------- Apple


def apple_payload(**extra):
    return {"transactionId": "2000001", "originalTransactionId": "2000001", "bundleId": "com.oltivra.app",
            "productId": "remove_ads_forever", "inAppOwnershipType": "PURCHASED", "environment": "Sandbox", **extra}


def test_apple_purchase_refund_and_restore(players, container, client):
    fake = container.purchases.apple
    res = players.post("/v1/purchases/verify/apple", "u1", {"signed_transaction": fake.encode(apple_payload())})
    assert res.json()["remove_ads"] is True
    notification = fake.encode({"notificationType": "REFUND", "data": {
        "bundleId": "com.oltivra.app", "signedTransactionInfo": fake.encode(apple_payload(revocationDate=1))}})
    assert client.post("/internal/purchases/apple-notifications", json={"signedPayload": notification}).status_code \
        == 200
    assert players.get("/v1/purchases/entitlements", "u1").json()["remove_ads"] is False
    reversed_ = fake.encode({"notificationType": "REFUND_REVERSED", "data": {
        "bundleId": "com.oltivra.app", "signedTransactionInfo": fake.encode(apple_payload())}})
    client.post("/internal/purchases/apple-notifications", json={"signedPayload": reversed_})
    assert players.get("/v1/purchases/entitlements", "u1").json()["remove_ads"] is True


def test_apple_wrong_bundle_and_bad_signature(players, container):
    fake = container.purchases.apple
    bad_bundle = players.post("/v1/purchases/verify/apple", "u1",
                              {"signed_transaction": fake.encode(apple_payload(bundleId="com.evil.app"))})
    assert bad_bundle.status_code == 402
    forged = jwt.encode(apple_payload(), "not-the-secret-at-all-000000000000", algorithm="HS256")
    assert players.post("/v1/purchases/verify/apple", "u1", {"signed_transaction": forged}).status_code == 402


def _cert(subject, issuer, public_key, signer, ca: bool):
    now = dt.datetime.now(dt.UTC)
    return (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)]))
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer)])).public_key(public_key)
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True).sign(signer, hashes.SHA256()))


def _chain():
    root_key, inter_key, leaf_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
    root = _cert("Test Root", "Test Root", root_key.public_key(), root_key, True)
    inter = _cert("Test Intermediate", "Test Root", inter_key.public_key(), root_key, True)
    leaf = _cert("Test Leaf", "Test Intermediate", leaf_key.public_key(), inter_key, False)
    x5c = [base64.b64encode(c.public_bytes(serialization.Encoding.DER)).decode() for c in (leaf, inter, root)]
    return root, leaf_key, x5c


def test_apple_jws_chain_verification():
    root, leaf_key, x5c = _chain()
    token = jwt.encode(apple_payload(), leaf_key, algorithm="ES256", headers={"x5c": x5c})
    assert AppleJwsVerifier([root]).decode(token)["transactionId"] == "2000001"
    other_root, _, _ = _chain()
    from app.common.errors import ApiError

    with pytest.raises(ApiError):
        AppleJwsVerifier([other_root]).decode(token)  # untrusted root
    _, other_leaf, _ = _chain()
    forged = jwt.encode(apple_payload(), other_leaf, algorithm="ES256", headers={"x5c": x5c})
    with pytest.raises(ApiError):
        AppleJwsVerifier([root]).decode(forged)  # signature does not match the chained leaf


def test_apple_reconciliation_detects_missed_refund(players, container):
    fake = container.purchases.apple
    players.post("/v1/purchases/verify/apple", "u1", {"signed_transaction": fake.encode(apple_payload())})
    store = container.purchases.apple_store
    assert asyncio.run(container.purchases.reconcile_apple()) == 0  # Apple has nothing newer
    store.transactions["2000001"] = fake.encode(apple_payload())
    assert asyncio.run(container.purchases.reconcile_apple()) == 0  # unchanged state
    store.transactions["2000001"] = fake.encode(apple_payload(revocationDate=1))
    assert asyncio.run(container.purchases.reconcile_apple()) == 1
    assert players.get("/v1/purchases/entitlements", "u1").json()["remove_ads"] is False


def test_app_store_server_api_token_is_es256_with_bundle():
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from app.purchases.verifiers import AppStoreServerApiClient

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    client = AppStoreServerApiClient(issuer_id="iss-1", key_id="KEY123", private_key_pem=pem,
                                     bundle_id="com.oltivra.app", environment="Sandbox", clock=lambda: 1_800_000_000)
    token = client.token()
    assert jwt.get_unverified_header(token)["kid"] == "KEY123"
    claims = jwt.decode(token, key.public_key(), algorithms=["ES256"], audience="appstoreconnect-v1",
                        options={"verify_exp": False, "verify_iat": False})
    assert claims["bid"] == "com.oltivra.app" and claims["iss"] == "iss-1"
