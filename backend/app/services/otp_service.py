"""
Phone & OTP Verification (concept paper Section 4.1). OTP codes are
generated with the OS CSPRNG, stored in Redis with a TTL, and delivered by
whichever SMS_PROVIDER is configured:

  - "twilio": calls the real Twilio Messages REST API over HTTPS with your
    account credentials (env vars). This is a standard telecom SMS gateway,
    not an LLM provider, and is what the concept paper's Technology Stack
    section (7) calls "SMS gateway for OTP verification".
  - "generic_http": POSTs to any SMS gateway you configure, for providers
    other than Twilio (Africa's Talking, Vonage, a national telco gateway,
    etc.) without code changes.
  - "console": logs the OTP instead of sending it. Only usable when
    ENVIRONMENT != production (Settings.require_production_safety enforces
    this at startup).
"""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

import httpx
import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger("pulsepin.otp")


class OTPError(Exception):
    pass


class OTPRateLimitError(OTPError):
    pass


class OTPInvalidError(OTPError):
    pass


class OTPService:
    def __init__(self, redis_client: aioredis.Redis) -> None:
        self.redis = redis_client
        self.settings = get_settings()

    def _code_key(self, phone_number: str) -> str:
        return f"otp:code:{phone_number}"

    def _attempts_key(self, phone_number: str) -> str:
        return f"otp:attempts:{phone_number}"

    def _cooldown_key(self, phone_number: str) -> str:
        return f"otp:cooldown:{phone_number}"

    async def request_otp(self, phone_number: str) -> None:
        if await self.redis.exists(self._cooldown_key(phone_number)):
            raise OTPRateLimitError("Please wait before requesting another code.")

        code = "".join(secrets.choice("0123456789") for _ in range(self.settings.OTP_LENGTH))

        await self.redis.set(
            self._code_key(phone_number), code, ex=self.settings.OTP_TTL_SECONDS
        )
        await self.redis.set(
            self._attempts_key(phone_number), 0, ex=self.settings.OTP_TTL_SECONDS
        )
        await self.redis.set(
            self._cooldown_key(phone_number),
            1,
            ex=self.settings.OTP_RESEND_COOLDOWN_SECONDS,
        )

        await self._send_sms(
            phone_number,
            f"Your PulsePin verification code is {code}. It expires in "
            f"{self.settings.OTP_TTL_SECONDS // 60} minutes. Never share this code.",
        )

    async def verify_otp(self, phone_number: str, submitted_code: str) -> bool:
        attempts_key = self._attempts_key(phone_number)
        attempts = await self.redis.incr(attempts_key)
        if attempts == 1:
            await self.redis.expire(attempts_key, self.settings.OTP_TTL_SECONDS)
        if attempts > self.settings.OTP_MAX_ATTEMPTS:
            raise OTPRateLimitError("Too many attempts. Request a new code.")

        stored_code = await self.redis.get(self._code_key(phone_number))
        if stored_code is None:
            raise OTPInvalidError("No active code for this number. Request a new one.")

        stored_code_str = stored_code.decode() if isinstance(stored_code, bytes) else stored_code
        if not secrets.compare_digest(stored_code_str, submitted_code):
            raise OTPInvalidError("Incorrect code.")

        await self.redis.delete(self._code_key(phone_number))
        await self.redis.delete(attempts_key)
        return True

    async def _send_sms(self, phone_number: str, message: str) -> None:
        provider = self.settings.SMS_PROVIDER
        if provider == "console":
            logger.warning("SMS[console-dev]: to=%s message=%s", phone_number, message)
            return

        if provider == "twilio":
            if not (self.settings.SMS_ACCOUNT_SID and self.settings.SMS_AUTH_TOKEN and self.settings.SMS_FROM_NUMBER):
                raise OTPError("Twilio SMS provider selected but credentials are not configured.")
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self.settings.SMS_ACCOUNT_SID}/Messages.json"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    data={"To": phone_number, "From": self.settings.SMS_FROM_NUMBER, "Body": message},
                    auth=(self.settings.SMS_ACCOUNT_SID, self.settings.SMS_AUTH_TOKEN),
                )
                resp.raise_for_status()
            return

        if provider == "generic_http":
            if not self.settings.SMS_GENERIC_HTTP_URL:
                raise OTPError("generic_http SMS provider selected but SMS_GENERIC_HTTP_URL is not set.")
            headers = {}
            if self.settings.SMS_GENERIC_HTTP_API_KEY:
                headers["Authorization"] = f"Bearer {self.settings.SMS_GENERIC_HTTP_API_KEY}"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self.settings.SMS_GENERIC_HTTP_URL,
                    json={"to": phone_number, "message": message},
                    headers=headers,
                )
                resp.raise_for_status()
            return

        raise OTPError(f"Unknown SMS_PROVIDER: {provider}")


_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
    return _redis_client


async def get_otp_service() -> OTPService:
    return OTPService(await get_redis())
