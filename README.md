# PulsePin

AI-assisted symptom triage, capability-matched hospital routing, and
verified emergency dispatch with live ambulance tracking — implementing
the PulsePin Concept Paper, Security Architecture spec, and the supplied
anti-prank/abuse-prevention design.

Runs on **web, iOS, and Android** from one codebase (see
`MOBILE_BUILDS.md`).

## What's actually real vs. what's a documented gap

This codebase does not claim more than it delivers. Read `LIMITATIONS.md`
and `SECURITY.md` before treating anything here as production-ready as-is
— both files exist specifically to separate "implemented and tested" from
"designed but needs a real credential/dataset/account to finish" from
"genuinely not done yet." Every ML component was trained and evaluated on
real data (never mocked), every migration was run against a live
PostgreSQL+PostGIS database, and the test suite (19 tests) was executed,
not just written.

## Architecture

```
pulsepin/
  backend/                FastAPI + PostgreSQL/PostGIS + Redis
    app/
      api/routes/          auth, triage, hospitals, dispatch, admin, ws
      core/                config, security/JWT, MFA, rate limiting, encryption
      ml/                  triage model, dispatch confidence engine, training scripts
      models/               SQLAlchemy ORM (users, hospitals, triage, dispatch)
      services/            OTP/SMS, facility matching, audit log, kill switch, captcha
    alembic/               real, tested database migrations
  frontend-patient/        React + Vite -- web, PWA, and Capacitor iOS/Android wrapper
  frontend-dispatcher/     React + Vite -- hospital dispatcher dashboard (web)
  infra/traefik/           reverse proxy: TLS, rate limiting, IP allow-listing
  docker-compose.yml       full stack, network-segmented
```

## Quick start (local dev)

```bash
cp .env.example .env
# edit .env: at minimum set SECRET_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD
docker compose up --build
```

- Patient app: http://localhost:5173
- Dispatcher dashboard: http://localhost:5174
- Backend API docs: http://localhost:8000/api/docs
- `SMS_PROVIDER=console` by default -- OTP codes print to the backend log
  instead of being sent as real SMS, so you can log in without a Twilio
  account.

Seed demo hospitals:
```bash
docker compose exec backend python -m app.db.seed
```

## Running the backend outside Docker

```bash
cd backend
pip install -r requirements.txt --break-system-packages
export ENVIRONMENT=development SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/pulsepin"
export REDIS_URL="redis://localhost:6379/0"
python -m alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload
```

## Training / retraining the triage model

```bash
cd backend
python -m app.ml.train_triage_model      # trains XGBoost, writes artifacts + honest metrics
python -m app.ml.build_symptom_stats     # builds the info-gain question-selection table
python -m app.ml.audit_dataset           # prints a bias/quality report -- READ THIS
```

## Tests

```bash
cd backend
python -m pytest app/tests/ -v
```

## Mobile builds

See `MOBILE_BUILDS.md` for the full iOS/Android build steps, required
native permission entries, and what Capacitor does and doesn't give you
out of the box.

**Publishing to the App Store / Play Store:** see `PUBLISHING.md` for a
complete, ordered runbook -- every known rejection trigger for this app
category (emergency-services disclaimers, privacy/data-safety forms,
placeholder bundle IDs, background location justification, etc.) and
exactly what's already fixed in code vs. what's a business/legal step
only you can complete.

## Production deployment

```bash
docker compose -f docker-compose.yml --profile prod up --build
```

Before doing this for real:
1. Read `SECURITY.md` top to bottom.
2. Set `ENABLE_LIVE_DISPATCH=true` **and** `SECURITY_SIGNOFF_COMPLETED=true`
   only after an actual legal review and penetration test -- the app
   refuses to start with live dispatch enabled otherwise
   (`app/core/config.py::require_production_safety`).
3. Set real `FIELD_ENCRYPTION_KEY` / `TOKENIZATION_KEY` / `SECRET_KEY`
   values and get them into a real secrets manager, not `.env` on disk.
4. Configure `infra/traefik/dynamic.yml`'s `admin-ipallowlist` -- it ships
   fail-closed (empty allow-list) on purpose.
5. Put a real WAF in front (see SECURITY.md Section 3).

## Documents this implements

- `PulsePin_Concept_Paper.docx` -- product/technical concept
- `PulsePin_Security_Architecture.docx` -- security control specification
- The supplied anti-prank / abuse-prevention behavioral spec (phone/device
  binding, human triage callback, GPS telemetry matching, financial/legal
  deterrence, behavioral anomaly detection)
