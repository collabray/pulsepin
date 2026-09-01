"""
Bot detection on signup/OTP (Security Architecture Section 5). Verifies a
CAPTCHA token against the real provider verify endpoint. Disabled
(CAPTCHA_PROVIDER="none") by default for local development; the code path
is real and production-ready once a provider is configured — it is not a
mock.

Note: the provider's verify endpoint (challenges.cloudflare.com or
hcaptcha.com) must be reachable from wherever this runs; add it to your
deployment's network egress allow-list.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings


class CaptchaError(Exception):
    pass


DEFAULT_VERIFY_URLS = {
    "turnstile": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    "hcaptcha": "https://hcaptcha.com/siteverify",
}


async def verify_captcha(token: str, remote_ip: str | None = None) -> bool:
    settings = get_settings()
    if settings.CAPTCHA_PROVIDER == "none":
        return True  # explicitly disabled; caller should only skip this in dev

    if not settings.CAPTCHA_SECRET_KEY:
        raise CaptchaError("CAPTCHA_PROVIDER is set but CAPTCHA_SECRET_KEY is missing.")

    verify_url = settings.CAPTCHA_VERIFY_URL or DEFAULT_VERIFY_URLS.get(settings.CAPTCHA_PROVIDER)
    if not verify_url:
        raise CaptchaError(f"No verify URL configured for provider {settings.CAPTCHA_PROVIDER}.")

    payload = {"secret": settings.CAPTCHA_SECRET_KEY, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.post(verify_url, data=payload)
        resp.raise_for_status()
        result = resp.json()

    return bool(result.get("success"))
