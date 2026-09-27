"""Player identity: consent record, global username registry, curated avatar, preferences, public profile.

``users/{uid}`` is server-only (it holds MMR). ``public_profiles/{public_id}`` is the minimum safe public
projection (spec §6.1). ``public_ids/{public_id}`` maps the UID-derived public ID back to the UID.
"""

from __future__ import annotations

from typing import Any

from app.catalog.service import CatalogService
from app.common.clock import Clock
from app.common.errors import ApiError, ErrorCode
from app.common.keys import Keyring
from app.common.store.docstore import DocStore
from app.ranking.leagues import display_league
from app.ranking.levels import level_for_xp
from app.usernames.rules import check_username, normalize

TERMS_VERSION = "2026-09"
PRIVACY_VERSION = "2026-09"
USERNAME_COOLDOWN_MS = 30 * 86_400_000
USERNAME_RESERVATION_MS = 30 * 86_400_000
BLOCKLIST_PATH = "moderation_config/username_blocklist"


def user_path(uid: str) -> str:
    return f"users/{uid}"


def registry_path(normalized: str) -> str:
    return f"username_registry/{normalized}"


def new_user(uid: str, public_id: str, now_ms: int, start_mmr: int = 1000) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "uid": uid,
        "public_id": public_id,
        "username_display": None,
        "username_normalized": None,
        "avatar_id": None,
        "frame_id": "frame_none",
        "featured_badge_ids": [],
        "created_at_ms": now_ms,
        "age_gate_passed": False,
        "question_language": "en",
        "ui_language": "en",
        "notifications": {"friend_requests": True, "challenges": True, "leaderboard": True, "missions": True,
                          "league": True},
        "total_xp": 0,
        "mmr": start_mmr,
        "placement_matches_completed": 0,
        "ranked_matches_completed": 0,
        "quick_current_ranked_win_streak": 0,
        "quick_best_ranked_win_streak": 0,
        "survival_ranked_crowns_lifetime": 0,
        "quick_ranked_wins_lifetime": 0,
        "quick_wins_lifetime": 0,
        "matches_completed": 0,
        "badge_ids": [],
        "frame_ids": ["frame_none"],
        "status": "ACTIVE",
        "progression_sequence": 0,
    }


class ProfileService:
    def __init__(self, store: DocStore, clock: Clock, keys: Keyring, catalog: CatalogService) -> None:
        self._store = store
        self._clock = clock
        self._keys = keys
        self._catalog = catalog

    def public_id(self, uid: str) -> str:
        return "p" + self._keys.username_hash.hexdigest(f"public-id:{uid}")[:19]

    async def uid_for_public_id(self, public_id: str) -> str:
        doc = await self._store.get(f"public_ids/{public_id}") if public_id else None
        if not doc:
            raise ApiError(ErrorCode.NOT_FOUND)
        return doc["uid"]

    # ---------------------------------------------------------------- consent
    async def record_consent(self, uid: str, age_confirmed: bool, terms_version: str, privacy_version: str) -> dict:
        if not age_confirmed:
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "age_gate_required"})
        if terms_version != TERMS_VERSION or privacy_version != PRIVACY_VERSION:
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "legal_version_outdated",
                                                              "terms_version": TERMS_VERSION,
                                                              "privacy_version": PRIVACY_VERSION})
        now = self._clock.now_ms()
        pid = self.public_id(uid)

        def txn_fn(txn) -> dict:
            user = txn.get(user_path(uid))
            user = user or new_user(uid, pid, now)
            if not user.get("age_gate_passed"):
                user["age_gate_passed"] = True
                user["age_gate_verified_at_ms"] = now
            # Exact date of birth is never collected or stored (spec §2.1).
            user.update(terms_version=terms_version, terms_accepted_at_ms=now, privacy_version=privacy_version,
                        privacy_accepted_at_ms=now)
            txn.set(user_path(uid), user)
            txn.set(f"public_ids/{pid}", {"uid": uid, "schema_version": 1})
            return user

        return await self._store.run_transaction(txn_fn)

    # ---------------------------------------------------------------- username
    async def _blocklist(self) -> tuple[str, ...]:
        doc = await self._store.get(BLOCKLIST_PATH)
        return tuple((doc or {}).get("fragments", ()))

    async def check_availability(self, uid: str, username: str) -> dict:
        problem = check_username(username, await self._blocklist())
        if problem:
            return {"available": False, "reason": problem.value}
        reg = await self._store.get(registry_path(normalize(username)))
        now = self._clock.now_ms()
        if reg and not self._registry_allows(reg, uid, now):
            return {"available": False, "reason": "TAKEN"}
        return {"available": True, "reason": None}

    @staticmethod
    def _registry_allows(reg: dict[str, Any], uid: str, now_ms: int) -> bool:
        if reg.get("state") == "ACTIVE":
            return reg.get("uid") == uid
        if reg.get("state") == "RESERVED" and reg.get("reserved_until_ms", 0) > now_ms:
            return reg.get("reserved_for_uid") == uid
        return True

    async def claim_username(self, uid: str, username: str, *, change: bool) -> dict:
        problem = check_username(username, await self._blocklist())
        if problem:
            raise ApiError(ErrorCode.USERNAME_INVALID, detail={"reason": problem.value})
        norm = normalize(username)
        now = self._clock.now_ms()

        def txn_fn(txn) -> dict:
            user, reg = txn.get_many([user_path(uid), registry_path(norm)])
            if not user or not user.get("age_gate_passed"):
                raise ApiError(ErrorCode.PROFILE_INCOMPLETE, detail={"reason": "consent_required"})
            old_norm = user.get("username_normalized")
            if old_norm == norm and user.get("username_display") == username:
                return user
            if not change and old_norm:
                raise ApiError(ErrorCode.CONFLICT, detail={"reason": "use_username_change"})
            if change:
                if not old_norm:
                    raise ApiError(ErrorCode.CONFLICT, detail={"reason": "no_username_yet"})
                last = user.get("username_changed_at_ms") or user.get("username_claimed_at_ms") or 0
                forced = user.get("rename_required", False)
                if not forced and now - last < USERNAME_COOLDOWN_MS:
                    raise ApiError(ErrorCode.USERNAME_COOLDOWN,
                                   detail={"available_at_ms": last + USERNAME_COOLDOWN_MS})
            if reg and not self._registry_allows(reg, uid, now):
                raise ApiError(ErrorCode.USERNAME_TAKEN)
            txn.set(registry_path(norm), {"schema_version": 1, "state": "ACTIVE", "uid": uid, "is_bot": False,
                                          "name": norm, "updated_at_ms": now})
            if old_norm and old_norm != norm:
                txn.set(registry_path(old_norm), {"schema_version": 1, "state": "RESERVED", "uid": None,
                                                  "reserved_for_uid": uid,
                                                  "reserved_until_ms": now + USERNAME_RESERVATION_MS,
                                                  "updated_at_ms": now})
            updates = {"username_display": username, "username_normalized": norm}
            if change:
                updates["username_changed_at_ms"] = now
                updates["rename_required"] = False
            else:
                updates["username_claimed_at_ms"] = now
            txn.update(user_path(uid), updates)
            return {**user, **updates}

        user = await self._store.run_transaction(txn_fn)
        await self.sync_public_profile(user)
        return user

    # ---------------------------------------------------------------- avatar / preferences / cosmetics
    async def set_avatar(self, uid: str, avatar_id: str) -> dict:
        if not await self._catalog.is_active_avatar(avatar_id):
            raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "avatar_not_in_catalog"})
        user = await self._require_user(uid)
        await self._store.update(user_path(uid), {"avatar_id": avatar_id})
        user["avatar_id"] = avatar_id
        await self.sync_public_profile(user)
        return user

    async def set_preferences(self, uid: str, *, question_language: str | None, ui_language: str | None,
                              notifications: dict[str, bool] | None, competitive_languages: list[str],
                              ui_languages: list[str]) -> dict:
        user = await self._require_user(uid)
        updates: dict[str, Any] = {}
        if question_language is not None:
            # No silent fallback to another competitive language (spec §2.4).
            if question_language not in competitive_languages:
                raise ApiError(ErrorCode.FEATURE_DISABLED, detail={"reason": "question_language_unavailable"})
            updates["question_language"] = question_language
        if ui_language is not None:
            if ui_language not in ui_languages:
                raise ApiError(ErrorCode.INVALID_REQUEST, detail={"reason": "ui_language_unsupported"})
            updates["ui_language"] = ui_language
        if notifications is not None:
            allowed = set(user.get("notifications", {}))
            updates["notifications"] = {**user.get("notifications", {}),
                                        **{k: bool(v) for k, v in notifications.items() if k in allowed}}
        if updates:
            await self._store.update(user_path(uid), updates)
        return {**user, **updates}

    async def equip(self, uid: str, frame_id: str | None, featured_badge_ids: list[str] | None) -> dict:
        user = await self._require_user(uid)
        updates: dict[str, Any] = {}
        if frame_id is not None:
            if frame_id not in user.get("frame_ids", ["frame_none"]):
                raise ApiError(ErrorCode.FORBIDDEN, detail={"reason": "frame_not_earned"})
            updates["frame_id"] = frame_id
        if featured_badge_ids is not None:
            if len(featured_badge_ids) > 3 or not set(featured_badge_ids) <= set(user.get("badge_ids", [])):
                raise ApiError(ErrorCode.FORBIDDEN, detail={"reason": "badge_not_earned"})
            updates["featured_badge_ids"] = featured_badge_ids
        if updates:
            await self._store.update(user_path(uid), updates)
        user = {**user, **updates}
        await self.sync_public_profile(user)
        return user

    async def _require_user(self, uid: str) -> dict:
        user = await self._store.get(user_path(uid))
        if not user or not user.get("age_gate_passed"):
            raise ApiError(ErrorCode.PROFILE_INCOMPLETE, detail={"reason": "consent_required"})
        return user

    # ---------------------------------------------------------------- projections
    async def sync_public_profile(self, user: dict[str, Any]) -> None:
        if not user.get("username_display"):
            return
        await self._store.set(f"public_profiles/{user['public_id']}", self.public_profile(user))

    def public_profile(self, user: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "public_id": user["public_id"],
            "username_display": user.get("username_display"),
            "avatar_id": user.get("avatar_id"),
            "frame_id": user.get("frame_id", "frame_none"),
            "featured_badge_ids": user.get("featured_badge_ids", []),
            "league": display_league(user.get("mmr", 1000), user.get("placement_matches_completed", 0)).value,
            "level": level_for_xp(user.get("total_xp", 0)),
            "quick_best_ranked_win_streak": user.get("quick_best_ranked_win_streak", 0),
            "survival_ranked_crowns_lifetime": user.get("survival_ranked_crowns_lifetime", 0),
            "quick_ranked_wins_lifetime": user.get("quick_ranked_wins_lifetime", 0),
        }

    def own_profile(self, user: dict[str, Any], entitlement: dict[str, Any] | None = None) -> dict[str, Any]:
        """Safe self view: never raw MMR, internal risk score or moderation notes."""
        from app.ranking.leagues import league_progress
        from app.ranking.levels import level_progress

        last_change = user.get("username_changed_at_ms") or user.get("username_claimed_at_ms")
        return {
            **self.public_profile(user),
            "onboarding": {
                "consent": bool(user.get("age_gate_passed")) and user.get("terms_version") == TERMS_VERSION
                           and user.get("privacy_version") == PRIVACY_VERSION,
                "username": bool(user.get("username_normalized")),
                "avatar": bool(user.get("avatar_id")),
                "rename_required": bool(user.get("rename_required")),
            },
            "total_xp": user.get("total_xp", 0),
            "level_progress": level_progress(user.get("total_xp", 0)),
            "league_progress": league_progress(user.get("mmr", 1000), user.get("placement_matches_completed", 0)),
            "quick_current_ranked_win_streak": user.get("quick_current_ranked_win_streak", 0),
            "matches_completed": user.get("matches_completed", 0),
            "question_language": user.get("question_language", "en"),
            "ui_language": user.get("ui_language", "en"),
            "notifications": user.get("notifications", {}),
            "badge_ids": user.get("badge_ids", []),
            "frame_ids": user.get("frame_ids", ["frame_none"]),
            "username_change_available_at_ms": (last_change + USERNAME_COOLDOWN_MS) if last_change else None,
            "status": user.get("status", "ACTIVE"),
            "remove_ads": bool(entitlement and entitlement.get("remove_ads") and entitlement.get("state") == "ACTIVE"),
        }
