"""
VoIP / burner-number detection (supplied anti-prank spec: "VoIP/burner
numbers are automatically flagged"). Uses Twilio's Lookup v2 API with the
line_type_intelligence package — a standard telecom carrier-data API, not
an LLM provider, and the same category of service the concept paper's
tech stack calls for ("SMS gateway"). Real HTTP call to a real endpoint;
disabled by default (ENABLE_LINE_TYPE_LOOKUP=false) until Twilio
credentials are configured, so local dev doesn't require an account.
"""
from __future__ import annotations

import httpx

from app.core.config import get_settings


class LineTypeLookupError(Exception):
    pass


async def lookup_line_type(phone_number: str) -> tuple[str, bool]:
    """
    Returns (line_type, is_voip_flagged). line_type is one of
    "mobile" / "landline" / "voip" / "unknown".
    """
    settings = get_settings()
    if not settings.ENABLE_LINE_TYPE_LOOKUP:
        return "unknown", False

    if not (settings.TWILIO_LOOKUP_ACCOUNT_SID and settings.TWILIO_LOOKUP_AUTH_TOKEN):
        raise LineTypeLookupError("ENABLE_LINE_TYPE_LOOKUP is true but Twilio Lookup credentials are missing.")

    url = f"https://lookups.twilio.com/v2/PhoneNumbers/{phone_number}"
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(
            url,
            params={"Fields": "line_type_intelligence"},
            auth=(settings.TWILIO_LOOKUP_ACCOUNT_SID, settings.TWILIO_LOOKUP_AUTH_TOKEN),
        )
        resp.raise_for_status()
        data = resp.json()

    line_type = (
        data.get("line_type_intelligence", {}).get("type", "unknown") or "unknown"
    ).lower()
    is_voip = line_type in ("voip", "nonFixedVoip".lower(), "fixedvoip")
    return line_type, is_voip
