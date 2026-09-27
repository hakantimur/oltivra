"""Friends, search, challenges, parties, rematch and device registration (spec §6, §27.5, §34.2)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.common import rate_limit
from app.common.api import Caller, get_container, player, run_mutation
from app.container import Container

router = APIRouter(prefix="/v1")


class MutationBody(BaseModel):
    request_id: str


class FriendRequestBody(BaseModel):
    request_id: str
    target_public_id: str = Field(max_length=32)


class ChallengeBody(BaseModel):
    request_id: str
    friend_public_ids: list[str] = Field(min_length=1, max_length=3)
    question_language: str = Field(max_length=8)


class InviteAcceptBody(BaseModel):
    request_id: str
    accept_question_language: str = Field(max_length=8)


class DeviceBody(BaseModel):
    request_id: str
    token: str = Field(min_length=10, max_length=4096)
    platform: Literal["android", "ios"]


# ---------------------------------------------------------------------------------------------- friends
@router.get("/friends")
async def friends(caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    return await c.friends.overview(caller.uid)


@router.get("/users/search")
async def search(username: str = Query(min_length=1, max_length=32), caller: Caller = Depends(player),
                 c: Container = Depends(get_container)) -> dict:
    await c.rate_limiter.hit(rate_limit.USERNAME_SEARCH, caller.uid)
    return await c.friends.search(caller.uid, username)


@router.post("/friends/requests")
async def send_friend_request(body: FriendRequestBody, request: Request, caller: Caller = Depends(player),
                              c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        await c.rate_limiter.hit(rate_limit.FRIEND_REQUEST, caller.uid)
        return await c.friends.send_request(caller.uid, body.target_public_id)

    return await run_mutation(c, request, caller, "friends.request", body.model_dump(), handler)


@router.post("/friends/requests/{request_id}/accept")
async def accept_friend_request(request_id: str, body: MutationBody, request: Request,
                                caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.friends.respond(caller.uid, request_id, accept=True)

    return await run_mutation(c, request, caller, f"friends.accept.{request_id}", body.model_dump(), handler)


@router.post("/friends/requests/{request_id}/decline")
async def decline_friend_request(request_id: str, body: MutationBody, request: Request,
                                 caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.friends.respond(caller.uid, request_id, accept=False)

    return await run_mutation(c, request, caller, f"friends.decline.{request_id}", body.model_dump(), handler)


@router.delete("/friends/{public_id}")
async def remove_friend(public_id: str, body: MutationBody, request: Request, caller: Caller = Depends(player),
                        c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.friends.remove(caller.uid, public_id)

    return await run_mutation(c, request, caller, f"friends.remove.{public_id}", body.model_dump(), handler)


# ---------------------------------------------------------------------------------------------- challenges
@router.post("/challenges")
async def create_challenge(body: ChallengeBody, request: Request, caller: Caller = Depends(player),
                           c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.parties.create_challenge(caller.uid, body.friend_public_ids, body.question_language)

    return await run_mutation(c, request, caller, "challenges.create", body.model_dump(), handler)


@router.get("/challenges/invites")
async def my_invites(caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    return await c.parties.my_invites(caller.uid)


@router.post("/challenges/{invite_token}/accept")
async def accept_challenge(invite_token: str, body: InviteAcceptBody, request: Request,
                           caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.parties.accept_invite(caller.uid, invite_token, body.accept_question_language)

    return await run_mutation(c, request, caller, "challenges.accept", body.model_dump(), handler)


@router.post("/challenges/{invite_token}/decline")
async def decline_challenge(invite_token: str, body: MutationBody, request: Request,
                            caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.parties.decline_invite(caller.uid, invite_token)

    return await run_mutation(c, request, caller, "challenges.decline", body.model_dump(), handler)


@router.get("/parties/{party_id}")
async def get_party(party_id: str, caller: Caller = Depends(player), c: Container = Depends(get_container)) -> dict:
    return await c.parties.get(caller.uid, party_id)


@router.post("/parties/{party_id}/leave")
async def leave_party(party_id: str, body: MutationBody, request: Request, caller: Caller = Depends(player),
                      c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.parties.leave(caller.uid, party_id)

    return await run_mutation(c, request, caller, f"parties.leave.{party_id}", body.model_dump(), handler)


@router.post("/parties/{party_id}/start")
async def start_party(party_id: str, body: MutationBody, request: Request, caller: Caller = Depends(player),
                      c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.parties.start(caller.uid, party_id)

    return await run_mutation(c, request, caller, f"parties.start.{party_id}", body.model_dump(), handler)


# ---------------------------------------------------------------------------------------------- rematch
@router.post("/matches/{match_id}/rematch")
async def rematch(match_id: str, body: MutationBody, request: Request, caller: Caller = Depends(player),
                  c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.parties.request_rematch(caller.uid, match_id)

    return await run_mutation(c, request, caller, f"matches.rematch.{match_id}", body.model_dump(), handler)


@router.post("/rematches/{rematch_id}/accept")
async def accept_rematch(rematch_id: str, body: MutationBody, request: Request, caller: Caller = Depends(player),
                         c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        return await c.parties.accept_rematch(caller.uid, rematch_id)

    return await run_mutation(c, request, caller, f"rematches.accept.{rematch_id}", body.model_dump(), handler)


# ---------------------------------------------------------------------------------------------- devices
@router.post("/devices")
async def register_device(body: DeviceBody, request: Request, caller: Caller = Depends(player),
                          c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        await c.notifications.register_device(caller.uid, body.token, body.platform)
        return {"schema_version": 1, "registered": True}

    return await run_mutation(c, request, caller, "devices.register", body.model_dump(), handler)


@router.delete("/devices")
async def unregister_device(body: DeviceBody, request: Request, caller: Caller = Depends(player),
                            c: Container = Depends(get_container)) -> dict:
    async def handler() -> dict:
        await c.notifications.unregister_device(caller.uid, body.token)
        return {"schema_version": 1, "registered": False}

    return await run_mutation(c, request, caller, "devices.unregister", body.model_dump(), handler)
