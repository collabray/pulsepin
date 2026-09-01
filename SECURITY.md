# PulsePin — Security Implementation Status

This maps every control in `PulsePin_Security_Architecture.docx` to what's
actually implemented in this repository, and what's still an operational
task for whoever deploys it. Marked honestly — "documented/configured" is
not the same as "code-enforced," and this file says which is which.

## 1. Authentication & Identity

| Control | Status |
|---|---|
| MFA for privileged roles | **Implemented.** TOTP (`app/core/mfa.py`), enforced at login for `dispatcher`/`hospital_admin`/`platform_admin` (`app/api/routes/auth.py`). |
| Phishing-resistant MFA (FIDO2/hardware keys) | **Partial.** TOTP is meaningfully more phishing-resistant than SMS but not as resistant as WebAuthn/FIDO2. Wiring a real WebAuthn relying party (`webauthn`/`fido2` PyPI packages) is the natural next step — not done here; don't claim FIDO2-level protection until it is. |
| Short-lived tokens, refresh rotation | **Implemented.** Access tokens expire in `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30); refresh tokens are separate JWTs. Single-use refresh-token *rotation* (invalidating the old token on use) is not yet implemented — currently refresh tokens are valid until expiry, reusable. Add a refresh-token denylist (Redis) before production. |
| Device binding / new-device challenge | **Implemented.** `UserDevice` table + logic in `auth.py`'s `/otp/verify`; privileged roles always require MFA (stricter than "only on new device," simpler to audit). |
| Throttled/alerted login & MFA attempts | **Partial.** OTP attempts are rate-limited (`app/services/otp_service.py`, `OTP_MAX_ATTEMPTS`). MFA-verify itself is not yet separately rate-limited — add a `rate_limit()` dependency to `/auth/mfa/verify` before production, and wire a real alerting sink (PagerDuty/Slack webhook) for repeated failures. |

## 2. Authorization & Access Control

| Control | Status |
|---|---|
| RBAC | **Implemented.** `UserRole` enum + `require_roles()` dependencies (`app/api/deps.py`). |
| Tenant isolation | **Implemented.** `hospital_admin`/`dispatcher` actions check `user.hospital_id == target hospital_id` (see `hospitals.py`). Data is logically partitioned by `hospital_id` column, not separate schemas/databases — sufficient at this scale; revisit if a single shared Postgres becomes a compliance concern for a specific hospital partner. |
| Least-privilege service accounts | **Documented, not code-enforced.** Requires separate DB roles/credentials per service in your actual deployment (the `db` user in `.env.example` is a single shared account for simplicity). Production: create distinct Postgres roles for the backend app vs. any analytics/reporting job, each with only the grants it needs. |
| Just-in-time privilege elevation | **Not implemented.** No standing "temporary admin" mechanism exists; `platform_admin` is currently a standing role. This is a real gap for a production deployment — track it as a follow-up (e.g. time-boxed role grants via a small approval workflow). |

## 3. API & Network Security

| Control | Status |
|---|---|
| Per-endpoint rate limiting | **Implemented.** `app/core/rate_limit.py`, Redis-backed; strictest on `/auth/otp/request` and `/dispatch` (see `RATE_LIMIT_*` settings). Also layered at the edge via Traefik (`infra/traefik/dynamic.yml`). |
| Input validation | **Implemented.** Every endpoint uses Pydantic schemas (`app/schemas/schemas.py`) with explicit bounds (lat/lon ranges, string patterns, numeric limits). |
| Mutual TLS between internal services | **Not implemented in this repo.** Requires a service mesh (e.g. Istio/Linkerd) or manually issued internal certs — infra-level, out of scope for application code. Documented here so it isn't silently dropped: add before handling real PII in production. |
| WAF | **Partial.** Traefik provides rate limiting + header hardening. A real signature-based WAF (Cloudflare, AWS WAF, or the ModSecurity Traefik plugin) is not included — put one in front before going live, per the security doc's own requirement. |
| IP allow-listing for admin interfaces | **Implemented (config), not yet populated.** `infra/traefik/dynamic.yml`'s `admin-ipallowlist` middleware is wired to the dispatcher dashboard router but ships with an empty (fail-closed) source range — you must set your real network CIDR before it does anything useful. |

## 4. Data Protection

| Control | Status |
|---|---|
| TLS 1.3 in transit | **Implemented (infra).** Traefik terminates TLS via Let's Encrypt (`infra/traefik/traefik.yml`). |
| Encryption at rest | **Infra-level, not code-enforced.** Use your cloud provider's encrypted-volume feature for the Postgres/Redis data directories; not something application code can enforce. |
| Field-level encryption | **Implemented and wired.** `app/core/field_encryption.py` (Fernet) + `app/db/encrypted_types.py` (transparent SQLAlchemy `EncryptedString` type). `User.phone_number` is encrypted at rest; lookups use a separate deterministic `phone_number_token` (HMAC) column since Fernet ciphertext isn't equality-queryable. Verified end-to-end: application code sees plaintext, `SELECT phone_number FROM users` on the raw table returns ciphertext. GPS/location history (`LiveLocationPing`, `DispatchRequest.reported_location`) is **not yet** field-level-encrypted on top of PostGIS's native storage — extend `EncryptedString`-style wrapping there if your threat model requires it beyond disk/transport encryption. |
| Tokenization | **Implemented (utility), not yet wired everywhere it should be** — `tokenize()` exists in `field_encryption.py` but audit logs and other log lines don't yet consistently use it instead of raw phone numbers. |
| Data minimization | **Partial.** No automated retention/purge job for `LiveLocationPing` history exists yet — add a scheduled job to delete location trails past a defined retention window. |
| Secrets management | **Pattern implemented, vault integration not included.** All secrets are environment variables, never hardcoded (`app/core/config.py` requires them, refuses insecure defaults in production). Wiring an actual vault (HashiCorp Vault, AWS Secrets Manager) to inject those env vars at deploy time is an infra task for your deployment pipeline, not application code. |

## 5. Abuse Prevention

| Control | Status |
|---|---|
| CAPTCHA on signup/OTP | **Implemented, disabled by default.** `app/services/captcha_service.py` (Turnstile/hCaptcha), gated by `CAPTCHA_PROVIDER`. |
| Behavioral anomaly detection | **Implemented (baseline).** Burst-request and repeat-cancellation detection in `app/api/routes/dispatch.py::_detect_behavioral_anomalies`. This is intentionally simple, rule-based detection — see LIMITATIONS.md for why a real ML anomaly model isn't included yet. |
| Full dispatcher action audit logging | **Implemented.** `AuditLog` model + `app/services/audit_log.py`, wired into every dispatcher/admin action (reverse-call result, outcome, ambulance assignment, kill switch, capability toggles are the ones actively logged — extend the pattern to any new admin action you add). |

## 6. Infrastructure & Operational Security

| Control | Status |
|---|---|
| Network segmentation | **Implemented (compose topology).** `docker-compose.yml`'s `internal` network has no external route; only Traefik sits on `edge`. |
| Dependency/vulnerability scanning | **Not included.** Wire `pip-audit`/`npm audit` (or Dependabot/Snyk) into CI — this is a CI-pipeline concern, not something that ships in the app repo itself. |
| Immutable infra, signed deployments | **Not included.** Depends on your CI/CD platform (e.g. cosign-signed container images) — infra/pipeline concern. |
| Penetration testing gate before live dispatch | **Implemented as a code gate.** `SECURITY_SIGNOFF_COMPLETED` must be `true` (alongside `ENABLE_LIVE_DISPATCH`) or the app refuses to start in production (`app/core/config.py::require_production_safety`). The actual pen test itself is, correctly, a human process this flag represents — not something code can do for you. |

## 7. Incident Response

| Control | Status |
|---|---|
| Documented IR plan | **Not included** — this is an organizational document, not code. Write one before going live; it's out of scope for a codebase to provide. |
| Platform-wide dispatch kill switch | **Implemented.** Redis-backed, instant, no redeploy required (`app/services/kill_switch.py` + `/admin/kill-switch/*` endpoints). |
| Periodic access review | **Not automated.** `GET /admin/audit-log` gives you the raw material for a review; there's no scheduled report yet. |

## 8. Lessons from real-world breaches (Section 8 of the doc)

| Control | Status |
|---|---|
| Number-matching MFA, not push-approve | TOTP as implemented requires typing a code, not tapping "approve" — inherently immune to the specific "spam push notifications" fatigue attack described. |
| Hard MFA throttling | **Partial** — see Section 1 above (MFA-verify itself needs a rate limit added). |
| Context shown at MFA prompt | **Not implemented** — the TOTP flow here doesn't display device/location/IP context at prompt time. Add this to the frontend MFA screen before production. |
| Zero hardcoded/plaintext credentials | **Enforced by design** — `Settings` fields have no working defaults for secrets; add a pre-commit secret scanner (e.g. `gitleaks`) in CI to catch accidental additions. |
| Real network segmentation | Implemented at the compose level (see Section 6). |
| Mandatory anomaly detection on privileged accounts | **Not implemented** — current anomaly detection (`_detect_behavioral_anomalies`) covers patient dispatch abuse, not privileged-account access patterns. A real implementation would watch dispatcher/admin login patterns the same way. Flagged here as a genuine gap, not silently omitted.

---

**Honest summary:** the application-layer controls that code can actually enforce — RBAC, MFA, rate limiting, audit logging, encryption utilities, the kill switch, the pen-test gate — are implemented and tested. The controls that are fundamentally organizational or infrastructure-deployment concerns (vault, WAF appliance, mTLS mesh, IR plan, dependency scanning in CI) are documented and hooked where the code needs to interact with them, but they are not things a code deliverable can complete on your behalf — they need your team's deployment pipeline and processes.
