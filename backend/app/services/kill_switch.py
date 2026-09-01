"""
Platform-wide dispatch kill switch (Security Architecture Section 7):
"a fast, tested mechanism to disable automated dispatch entirely, falling
back to fully human-mediated dispatch, if the confidence engine or
authentication layer is ever suspected compromised."

Backed by Redis rather than a config flag so it can be flipped instantly
during an incident, without a redeploy, and takes effect for every backend
replica immediately (they all read the same Redis key).
"""
from __future__ import annotations

from app.core.config import get_settings
from app.services.otp_service import get_redis


async def is_dispatch_kill_switch_active() -> bool:
    settings = get_settings()
    redis = await get_redis()
    value = await redis.get(settings.KILL_SWITCH_REDIS_KEY)
    return value is not None


async def activate_kill_switch(reason: str) -> None:
    settings = get_settings()
    redis = await get_redis()
    await redis.set(settings.KILL_SWITCH_REDIS_KEY, reason)


async def deactivate_kill_switch() -> None:
    settings = get_settings()
    redis = await get_redis()
    await redis.delete(settings.KILL_SWITCH_REDIS_KEY)
