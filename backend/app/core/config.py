"""
Central application configuration.

Every value that differs between environments (dev/staging/prod) or that is
sensitive (secrets, credentials) is read from the environment. Nothing here
is hardcoded, and there are no default secrets that would silently work in
production. In production, the required variables below must be set or the
app refuses to start (see `Settings.require_production_safety`).
"""
from functools import lru_cache
import logging
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Environment ---
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False

    # --- API ---
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "PulsePin"

    # --- Security ---
    SECRET_KEY: str = Field(..., description="JWT signing secret. MUST be set via env var.")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    ALGORITHM: str = "HS256"

    # --- Database ---
    DATABASE_URL: str = Field(
        ..., description="postgresql+psycopg://user:pass@host:5432/pulsepin"
    )
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # --- Redis (rate limiting, ws pub/sub, OTP throttling) ---
    REDIS_URL: str = "redis://redis:6379/0"

    # --- CORS ---
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:5174"]

    # --- SMS / OTP provider (self-hosted or any SMS gateway; NOT an LLM API) ---
    SMS_PROVIDER: Literal["twilio", "console", "generic_http"] = "console"
    SMS_ACCOUNT_SID: str | None = None
    SMS_AUTH_TOKEN: str | None = None
    SMS_FROM_NUMBER: str | None = None
    SMS_GENERIC_HTTP_URL: str | None = None
    SMS_GENERIC_HTTP_API_KEY: str | None = None

    OTP_LENGTH: int = 6
    OTP_TTL_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 45

    # --- ML model artifact paths ---
    TRIAGE_MODEL_PATH: str = "app/ml/artifacts/triage_model.xgb.json"
    TRIAGE_LABEL_MAP_PATH: str = "app/ml/artifacts/triage_labels.json"
    TRIAGE_SYMPTOM_INDEX_PATH: str = "app/ml/artifacts/symptom_index.json"
    TRIAGE_CONFIDENCE_FLOOR: float = Field(
        0.35, description="Below this top-1 probability, the app refuses to name a single disease."
    )
    DISPATCH_MODEL_PATH: str = "app/ml/artifacts/dispatch_confidence.xgb.json"

    # --- Dispatch confidence tiers ---
    DISPATCH_HIGH_CONFIDENCE_THRESHOLD: float = 0.80
    DISPATCH_MEDIUM_CONFIDENCE_THRESHOLD: float = 0.45

    # --- Feature flags (Phase gating, matches concept paper Section 9) ---
    # Dispatch stays OFF until legal review + pilot hospital partnership are
    # recorded via ENABLE_LIVE_DISPATCH=true in a specific deployment's env.
    # This is a deliberate safety gate, not a placeholder.
    ENABLE_LIVE_DISPATCH: bool = False
    # A second, independent gate: even with ENABLE_LIVE_DISPATCH=true, live
    # dispatch requires a recorded security sign-off (penetration test +
    # incident-response plan reviewed), per Security Architecture Section 6
    # ("Regular penetration testing... treated as a hard gate before
    # enabling live emergency dispatch"). Both flags must be true.
    SECURITY_SIGNOFF_COMPLETED: bool = False

    # --- Field-level encryption & tokenization (Security Architecture 4) ---
    FIELD_ENCRYPTION_KEY: str | None = Field(
        None, description="Fernet key (32 url-safe base64 bytes) for encrypting phone numbers / GPS history."
    )
    TOKENIZATION_KEY: str | None = Field(
        None, description="HMAC key for one-way tokenization of sensitive identifiers in logs."
    )

    # --- Rate limiting (Security Architecture 3) ---
    RATE_LIMIT_OTP_PER_HOUR: int = 5
    RATE_LIMIT_DISPATCH_TRIGGER_PER_HOUR: int = 3
    RATE_LIMIT_DEFAULT_PER_MINUTE: int = 60

    # --- MFA (Security Architecture 1) ---
    MFA_REQUIRED_ROLES: list[str] = ["dispatcher", "hospital_admin", "platform_admin"]
    MFA_ISSUER_NAME: str = "PulsePin"

    # --- CAPTCHA (Security Architecture 5, "Bot detection on signup/OTP") ---
    CAPTCHA_PROVIDER: Literal["none", "turnstile", "hcaptcha"] = "none"
    CAPTCHA_SECRET_KEY: str | None = None
    CAPTCHA_VERIFY_URL: str | None = None  # e.g. https://challenges.cloudflare.com/turnstile/v0/siteverify

    # --- VoIP / burner number detection (Security Architecture spec doc) ---
    # Uses Twilio Lookup's line-type-intelligence add-on, a standard
    # telecom API — not an LLM provider. Off by default; enable once you
    # have a Twilio account configured.
    ENABLE_LINE_TYPE_LOOKUP: bool = False
    TWILIO_LOOKUP_ACCOUNT_SID: str | None = None
    TWILIO_LOOKUP_AUTH_TOKEN: str | None = None

    # --- Financial/legal deterrence (silent-override dispatch gating) ---
    REQUIRE_TERMS_ACCEPTANCE_FOR_SILENT_OVERRIDE: bool = True
    FALSE_DISPATCH_FEE_USD: float = 200.0

    # --- Dispatch kill switch (Security Architecture 7) ---
    # Read live (via Redis) rather than only at process start, so it can be
    # flipped instantly during an incident without a redeploy.
    KILL_SWITCH_REDIS_KEY: str = "pulsepin:dispatch_kill_switch"

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_must_be_strong(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long.")
        return v

    def model_post_init(self, __context) -> None:
        # Dev-only convenience: generate ephemeral encryption/tokenization
        # keys so `docker compose up` works without manual setup. This
        # NEVER runs outside ENVIRONMENT=development, and
        # require_production_safety() independently refuses to boot in
        # production without real, persistent keys — losing this ephemeral
        # dev key on restart just means old encrypted dev rows become
        # unreadable, which is an acceptable dev-only inconvenience, not a
        # production risk.
        if self.ENVIRONMENT == "development":
            if not self.FIELD_ENCRYPTION_KEY:
                from cryptography.fernet import Fernet

                object.__setattr__(self, "FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
                logging.getLogger("pulsepin.config").warning(
                    "FIELD_ENCRYPTION_KEY not set — generated an EPHEMERAL dev-only key. "
                    "Set a real, persistent FIELD_ENCRYPTION_KEY before storing any data "
                    "you want to keep across restarts."
                )
            if not self.TOKENIZATION_KEY:
                import secrets as _secrets

                object.__setattr__(self, "TOKENIZATION_KEY", _secrets.token_hex(32))
                logging.getLogger("pulsepin.config").warning(
                    "TOKENIZATION_KEY not set — generated an EPHEMERAL dev-only key."
                )

    def require_production_safety(self) -> None:
        """Called at startup. Fails fast rather than booting insecurely."""
        if self.ENVIRONMENT == "production":
            if self.DEBUG:
                raise RuntimeError("DEBUG must be false in production.")
            if self.SMS_PROVIDER == "console":
                raise RuntimeError(
                    "SMS_PROVIDER=console is a local-dev stub and cannot be used "
                    "in production; configure a real SMS gateway."
                )
            if "localhost" in self.DATABASE_URL or "127.0.0.1" in self.DATABASE_URL:
                raise RuntimeError("Refusing to start in production against a localhost database.")
            if not self.FIELD_ENCRYPTION_KEY or not self.TOKENIZATION_KEY:
                raise RuntimeError(
                    "FIELD_ENCRYPTION_KEY and TOKENIZATION_KEY must be set in production "
                    "(Security Architecture Section 4: field-level encryption)."
                )
            if self.ENABLE_LIVE_DISPATCH and not self.SECURITY_SIGNOFF_COMPLETED:
                raise RuntimeError(
                    "ENABLE_LIVE_DISPATCH=true requires SECURITY_SIGNOFF_COMPLETED=true "
                    "(Security Architecture Section 6: penetration testing is a hard gate "
                    "before enabling live dispatch, not an optional step)."
                )
            if self.CAPTCHA_PROVIDER == "none":
                logging.getLogger("pulsepin.config").warning(
                    "CAPTCHA_PROVIDER=none in production — OTP/signup endpoints are "
                    "unprotected against automated abuse (Security Architecture Section 5)."
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
