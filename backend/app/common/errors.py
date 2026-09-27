"""Error contract (spec §19.2)."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    APP_CHECK_FAILED = "APP_CHECK_FAILED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
    ACCOUNT_DELETION_PENDING = "ACCOUNT_DELETION_PENDING"
    RATE_LIMITED = "RATE_LIMITED"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    INVALID_REQUEST = "INVALID_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    ACTIVE_RUNTIME_CONFLICT = "ACTIVE_RUNTIME_CONFLICT"
    QUEUE_TICKET_NOT_ACTIVE = "QUEUE_TICKET_NOT_ACTIVE"
    MATCH_NOT_FOUND = "MATCH_NOT_FOUND"
    NOT_MATCH_PARTICIPANT = "NOT_MATCH_PARTICIPANT"
    ROUND_NOT_ACTIVE = "ROUND_NOT_ACTIVE"
    ROUND_EXPIRED = "ROUND_EXPIRED"
    ANSWER_ALREADY_SUBMITTED = "ANSWER_ALREADY_SUBMITTED"
    INVALID_OPTION = "INVALID_OPTION"
    REACTION_ALREADY_USED = "REACTION_ALREADY_USED"
    MATCH_SETTLEMENT_PENDING = "MATCH_SETTLEMENT_PENDING"
    PURCHASE_NOT_VERIFIED = "PURCHASE_NOT_VERIFIED"
    REWARD_NOT_VERIFIED = "REWARD_NOT_VERIFIED"
    # Additional product codes (same envelope).
    USERNAME_TAKEN = "USERNAME_TAKEN"
    USERNAME_INVALID = "USERNAME_INVALID"
    USERNAME_COOLDOWN = "USERNAME_COOLDOWN"
    PROFILE_INCOMPLETE = "PROFILE_INCOMPLETE"
    CAPACITY_UNAVAILABLE = "CAPACITY_UNAVAILABLE"
    FEATURE_DISABLED = "FEATURE_DISABLED"
    BLOCKED = "BLOCKED"
    PARTY_FULL = "PARTY_FULL"
    PARTY_EXPIRED = "PARTY_EXPIRED"
    REWARD_CAP_REACHED = "REWARD_CAP_REACHED"
    MISSION_NOT_COMPLETE = "MISSION_NOT_COMPLETE"
    INTERNAL = "INTERNAL"


_DEFAULT_STATUS: dict[ErrorCode, int] = {
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.APP_CHECK_FAILED: 401,
    ErrorCode.ACCOUNT_SUSPENDED: 403,
    ErrorCode.ACCOUNT_DELETION_PENDING: 403,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.IDEMPOTENCY_KEY_REUSED: 409,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.CONFLICT: 409,
    ErrorCode.ACTIVE_RUNTIME_CONFLICT: 409,
    ErrorCode.QUEUE_TICKET_NOT_ACTIVE: 409,
    ErrorCode.MATCH_NOT_FOUND: 404,
    ErrorCode.NOT_MATCH_PARTICIPANT: 403,
    ErrorCode.ROUND_NOT_ACTIVE: 409,
    ErrorCode.ROUND_EXPIRED: 409,
    ErrorCode.ANSWER_ALREADY_SUBMITTED: 409,
    ErrorCode.INVALID_OPTION: 400,
    ErrorCode.REACTION_ALREADY_USED: 409,
    ErrorCode.MATCH_SETTLEMENT_PENDING: 409,
    ErrorCode.PURCHASE_NOT_VERIFIED: 402,
    ErrorCode.REWARD_NOT_VERIFIED: 402,
    ErrorCode.USERNAME_TAKEN: 409,
    ErrorCode.USERNAME_INVALID: 400,
    ErrorCode.USERNAME_COOLDOWN: 409,
    ErrorCode.PROFILE_INCOMPLETE: 409,
    ErrorCode.CAPACITY_UNAVAILABLE: 503,
    ErrorCode.FEATURE_DISABLED: 409,
    ErrorCode.BLOCKED: 403,
    ErrorCode.PARTY_FULL: 409,
    ErrorCode.PARTY_EXPIRED: 409,
    ErrorCode.REWARD_CAP_REACHED: 409,
    ErrorCode.MISSION_NOT_COMPLETE: 409,
    ErrorCode.INTERNAL: 500,
}

_RETRYABLE = {ErrorCode.RATE_LIMITED, ErrorCode.CAPACITY_UNAVAILABLE, ErrorCode.INTERNAL}


class ApiError(Exception):
    """Raised anywhere in request handling; rendered as the §19.2 envelope."""

    def __init__(
        self,
        code: ErrorCode,
        *,
        status: int | None = None,
        retryable: bool | None = None,
        retry_after_s: int | None = None,
        detail: dict | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.status = status or _DEFAULT_STATUS.get(code, 400)
        self.retryable = code in _RETRYABLE if retryable is None else retryable
        self.retry_after_s = retry_after_s
        self.detail = detail or {}

    @property
    def message_key(self) -> str:
        return f"error.{self.code.value.lower()}"

    def envelope(self, request_id: str) -> dict:
        body: dict = {
            "code": self.code.value,
            "message_key": self.message_key,
            "retryable": self.retryable,
            "request_id": request_id,
        }
        if self.retry_after_s is not None:
            body["retry_after_s"] = self.retry_after_s
        if self.detail:
            body["detail"] = self.detail
        return {"error": body}
