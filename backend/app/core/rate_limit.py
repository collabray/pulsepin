"""
Per-endpoint rate limiting (Security Architecture Section 3), with the
strictest limits on the dispatch-trigger endpoint — "the platform's most
abuse-sensitive surface." Uses a Redis fixed-window counter: simple, fast,
horizontally scales across backend replicas (all replicas share the same
Redis), and correct enough for abuse-prevention purposes (a textbook
sliding-log algorithm would be more precise but is unnecessary overhead
here).
"""
from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.services.otp_service import get_redis


class RateLimiter:
    def __init__(self, *, key_prefix: str, limit: int, window_seconds: int) -> None:
        self.key_prefix = key_prefix
        self.limit = limit
        self.window_seconds = window_seconds

    async def __call__(self, request: Request) -> None:
        identity = self._identify(request)
        redis = await get_redis()
        key = f"ratelimit:{self.key_prefix}:{identity}"

        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, self.window_seconds)

        if current > self.limit:
            ttl = await redis.ttl(key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {max(ttl, 1)} seconds.",
                headers={"Retry-After": str(max(ttl, 1))},
            )

    @staticmethod
    def _identify(request: Request) -> str:
        # Prefer the authenticated user if the auth dependency already ran
        # and set it on request.state; otherwise fall back to client IP.
        # (Trusting X-Forwarded-For requires the reverse proxy to strip any
        # client-supplied value first — enforced at the Traefik/WAF layer,
        # see infra/traefik/.)
        user = getattr(request.state, "user_id", None)
        if user:
            return f"user:{user}"
        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if not client_ip and request.client:
            client_ip = request.client.host
        return f"ip:{client_ip or 'unknown'}"


def rate_limit(key_prefix: str, limit: int, window_seconds: int) -> RateLimiter:
    return RateLimiter(key_prefix=key_prefix, limit=limit, window_seconds=window_seconds)
