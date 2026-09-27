"""Rewarded XP offers and Remove Ads purchase endpoints (spec §27.6, §31)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.common import rate_limit
from app.common.api import Caller, get_container, player, run_mutation
from app.container import Container

router = APIRouter(prefix="/v1")


class MutationBody(BaseModel):
    request_id: str


class GoogleVerifyBody(BaseModel):
    request_id: str
    product_id: str = Field(max_length=64)
    purchase_token: str = Field(min_length=8, max_length=4096)


class AppleVerifyBody(BaseModel):
    request_id: str
    signed_transaction: str = Field(min_length=16, max_length=32_768)


@router.post("/rewards/offers/{match_id}/start")
async def start_reward_offer(match_id: str, body: MutationBody, request: Request, caller: Caller = Depends(player),
                             c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        await c.rate_limiter.hit(rate_limit.REWARD_OFFER, caller.uid)
        return await c.rewards.start(caller.uid, match_id)

    return await run_mutation(c, request, caller, f"rewards.start.{match_id}", body.model_dump(), handler)


@router.get("/rewards/offers/{match_id}")
async def reward_offer_status(match_id: str, caller: Caller = Depends(player),
                              c: Container = Depends(get_container)) -> dict:
    return await c.rewards.status(caller.uid, match_id)


@router.post("/purchases/verify/google")
async def verify_google(body: GoogleVerifyBody, request: Request, caller: Caller = Depends(player),
                        c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.purchases.verify_google(caller.uid, body.product_id, body.purchase_token)

    return await run_mutation(c, request, caller, "purchases.verify.google", body.model_dump(), handler)


@router.post("/purchases/verify/apple")
async def verify_apple(body: AppleVerifyBody, request: Request, caller: Caller = Depends(player),
                       c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.purchases.verify_apple(caller.uid, body.signed_transaction)

    return await run_mutation(c, request, caller, "purchases.verify.apple", body.model_dump(), handler)


@router.get("/purchases/entitlements")
async def entitlements(caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    return await c.purchases.entitlements(caller.uid)
