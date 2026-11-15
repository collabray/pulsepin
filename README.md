# PulsePin

**The right hospital, the right ambulance, the first time.**

PulsePin is an emergency-response platform that combines AI-assisted symptom triage, capability-matched hospital routing, and verified dispatch with live ambulance tracking. It runs on web, iOS, and Android from a single codebase.

> **Status:** working, tested prototype, ready for pilot partnerships and seed-stage investment. See [Where we are](#where-we-are) for an honest account of what is built and what funding unlocks.

---

## The problem

When an emergency happens, people lose time on three decisions they are poorly placed to make:

1. **How serious is this?** Callers under stress under-triage or over-triage.
2. **Where should the patient go?** The nearest hospital is not always the one equipped for a stroke, trauma, or obstetric emergency.
3. **Is this call real?** Emergency systems are burdened by prank and abusive calls, which pull ambulances away from genuine cases.

## The solution

PulsePin addresses all three in one flow:

| Capability | What it does |
|---|---|
| **AI-assisted triage** | An XGBoost model plus an information-gain question selector asks the fewest, most useful questions to estimate urgency. |
| **Capability-matched routing** | Matches the patient to a facility that can treat their condition, not just the closest one, using PostGIS geospatial queries. |
| **Verified dispatch** | A dispatch confidence engine and human triage callback gate every live dispatch. |
| **Live ambulance tracking** | Real-time position updates for patients and hospital dispatchers over WebSockets. |
| **Anti-abuse by design** | Phone and device binding, GPS telemetry matching, behavioral anomaly detection, and financial/legal deterrence protect responders' time. |

## Why it can win

- **Abuse prevention is built in from the start.** Most triage apps treat prank calls as an afterthought. PulsePin's verification layer is part of the core dispatch path.
- **Routing by capability, not distance.** Sending a patient to the right facility the first time is where minutes and outcomes are saved.
- **Safety-first engineering.** The app refuses to start with live dispatch enabled unless legal review and penetration testing are formally signed off (`require_production_safety`). Responsible deployment is enforced in code, not left to a checklist.
- **One codebase, every platform.** Web, PWA, iOS, and Android via React and Capacitor, plus a separate hospital dispatcher dashboard.
- **Radical honesty about maturity.** Every ML component is trained and evaluated on real data. Limitations are documented in `LIMITATIONS.md` and `SECURITY.md`, which builds trust with clinical, legal, and procurement partners.

---

## Where we are

| Area | Status |
|---|---|
| Backend API (auth, triage, hospitals, dispatch, admin, WebSockets) | Built |
| Triage ML model and symptom question-selection | Trained and evaluated on real data, with a dataset bias/quality audit script |
| Database schema and migrations | Run against live PostgreSQL + PostGIS |
| Automated tests | 19 tests, executed |
| Patient app (web / PWA / iOS / Android) | Built |
| Dispatcher dashboard | Built |
| Security architecture (MFA, field encryption, rate limiting, audit log, kill switch, reverse-proxy hardening) | Implemented; independent penetration test pending |
| Store publishing runbook | Written (`PUBLISHING.md`) |
| Live emergency dispatch | **Intentionally disabled** until legal review, penetration test, and clinical validation are complete |

## What funding unlocks

Capital moves PulsePin from a tested prototype to a pilot-ready service. *(Adjust the allocation to your actual plan.)*

1. **Clinical validation:** partner with clinicians and run a prospective evaluation of the triage model against clinician judgment.
2. **Security and legal sign-off:** independent penetration test, legal and regulatory review, and the WAF and secrets-management infrastructure for production.
3. **Real-world data and partnerships:** onboard pilot hospitals and ambulance operators, and integrate with existing dispatch systems.
4. **Live dispatch pilot:** enable verified dispatch in a controlled region with human oversight.
5. **Team:** clinical advisor, ML/safety engineer, and partnerships lead.

## Roadmap

- **Now:** prototype complete and documented.
- **Next:** clinical advisory board, security audit, pilot partner agreements.
- **Then:** controlled live-dispatch pilot in one region.
- **Later:** multi-region expansion, integration with public emergency services, expanded condition coverage.

---

## Architecture

```
pulsepin/
  backend/                FastAPI + PostgreSQL/PostGIS + Redis
    app/
      api/routes/         auth, triage, hospitals, dispatch, admin, ws
      core/               config, JWT security, MFA, rate limiting, encryption
      ml/                 triage model, dispatch confidence engine, training scripts
      models/             SQLAlchemy ORM (users, hospitals, triage, dispatch)
      services/           OTP/SMS, facility matching, audit log, kill switch, captcha
    alembic/              tested database migrations
  frontend-patient/       React + Vite: web, PWA, Capacitor iOS/Android
  frontend-dispatcher/    React + Vite: hospital dispatcher dashboard
  infra/traefik/          reverse proxy: TLS, rate limiting, IP allow-listing
  docker-compose.yml      full stack, network-segmented
```

## Try it

```bash
cp .env.example .env
# edit .env: at minimum set SECRET_KEY, POSTGRES_PASSWORD, REDIS_PASSWORD
docker compose up --build
docker compose exec backend python -m app.db.seed   # demo hospitals
```

- Patient app: http://localhost:5173
- Dispatcher dashboard: http://localhost:5174
- API docs: http://localhost:8000/api/docs
- `SMS_PROVIDER=console` by default, so OTP codes print to the backend log and no Twilio account is needed for a demo.

<details>
<summary>Run the backend without Docker, retrain the model, run tests</summary>

```bash
cd backend
pip install -r requirements.txt --break-system-packages
export ENVIRONMENT=development SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/pulsepin"
export REDIS_URL="redis://localhost:6379/0"
python -m alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload

# Retrain the triage model
python -m app.ml.train_triage_model
python -m app.ml.build_symptom_stats
python -m app.ml.audit_dataset

# Tests
python -m pytest app/tests/ -v
```
</details>

## Production safety

Live dispatch will not start unless `ENABLE_LIVE_DISPATCH=true` **and** `SECURITY_SIGNOFF_COMPLETED=true` are both set. Before any production deployment:

1. Read `SECURITY.md` in full.
2. Complete legal review and a penetration test.
3. Use real `FIELD_ENCRYPTION_KEY`, `TOKENIZATION_KEY`, and `SECRET_KEY` values in a secrets manager.
4. Configure `admin-ipallowlist` in `infra/traefik/dynamic.yml` (ships fail-closed).
5. Place a WAF in front of the stack.

## Documentation

- `PulsePin_Concept_Paper.docx`: product and technical concept
- `PulsePin_Security_Architecture.docx`: security control specification
- `SECURITY.md` and `LIMITATIONS.md`: what is implemented versus what remains
- `MOBILE_BUILDS.md` and `PUBLISHING.md`: iOS/Android builds and store submission

## Partner with us

We are seeking **investors, hospital and ambulance-service pilot partners, clinical advisors, and grant funders** who want to make emergency response faster, fairer, and harder to abuse.

**Contact:**  · bensonray25@gmmail.com

---

*PulsePin is a decision-support and dispatch-routing tool. It is not a substitute for professional medical judgment or for official emergency services.*
