# PulsePin — Known Limitations

Written so nobody discovers these the hard way in production. Organized
by area; each item says what's true today and what closing the gap
requires.

## Triage model & training data

- **The training dataset is small and synthetic-shaped.** 305 unique rows
  across 41 diseases (132 binary symptoms), sourced from a public
  GitHub mirror of a well-known Kaggle "Disease Prediction" dataset.
  Run `python -m app.ml.audit_dataset` — it will tell you, automatically,
  that classes are artificially uniform (every disease has ~5-10 rows) and
  that there are only ~7 distinct symptom patterns per disease on average.
  Real patients present far more ambiguously than this. Treat the model's
  reported test accuracy (~90%+) as an upper bound on a clean textbook
  case, not an estimate of real-world performance.
- **DDXPlus was identified as a much better dataset** (1.3M synthetic-but-
  clinically-modeled patients, CC-BY licensed, from a peer-reviewed Mila/
  academic release) but its data files are hosted on figshare, which
  wasn't reachable from this build environment's network allowlist. See
  `app/ml/load_ddxplus.py` — write the adapter's file-reading half once
  you've downloaded the real files, and the training pipeline (`train_
  triage_model.py`) will accept it as a drop-in replacement.
- **The epidemiological prior recalibration (`app/ml/prevalence_priors.py`)
  only has real sourced numbers for 2 of 41 conditions** (malaria and TB
  incidence in Kenya, cited to WHO). Every other condition is left at a
  neutral multiplier rather than a guessed one — extend this table only
  with real, cited, region-specific incidence data from a public-health
  partner.
- **No clinical/regulatory review has occurred.** This is a technical
  triage-assistance tool, not a certified medical device. Before real
  patients rely on it, get a licensed clinician to review the condition-
  to-urgency mapping (`app/ml/triage_engine.py`'s `EMERGENCY_CONDITIONS`
  / `SELF_CARE_CONDITIONS`) and the capability-requirement mapping
  (`app/services/facility_matching.py`'s `CONDITION_CAPABILITY_MAP`) —
  both are currently a reasonable engineering first pass, not a
  clinician-signed-off document.

## Facility data

- **Seed data is placeholder.** `app/db/seed.py` creates three real,
  named Nairobi hospitals at their real locations, but their listed
  *capabilities* are illustrative, not sourced from each hospital's
  actual current status. Every real hospital partner must confirm their
  own capabilities via `PATCH /hospitals/{id}/capabilities` before the
  match results shown to a patient can be trusted.
- **No automated staleness enforcement beyond a visible warning.** A
  hospital that never updates its capability data will keep showing up in
  results with a "may be outdated" flag (`capability_data_is_stale`)
  forever — there's no automatic de-listing or escalation to a human when
  data goes stale for a long time.

## Dispatch Confidence Engine

- **No trained ML model yet — by design, not oversight.** The concept
  paper specifies a gradient-boosted classifier trained on historical
  dispatch outcomes. That history doesn't exist for a platform with zero
  real dispatches. `app/ml/dispatch_confidence.py` ships a deterministic,
  auditable weighted scorer instead, plus `train_from_audit_log()`, which
  will train a real model automatically once 200+ outcome-labeled
  dispatch requests exist in the audit trail. Fabricating training data
  to ship an ML model on day one would have meant the model learned
  invented abuse patterns and presented them as real — worse than not
  having ML yet.
- **Speed-between-consecutive-GPS-pings spoof detection is not wired up**
  (`implied_speed_kmh_since_last_ping` is always `None` today). It
  requires a location-history table keyed by user across sessions,
  distinct from the per-dispatch `LiveLocationPing` log that exists now —
  a real but modest addition.
- **`travel_time_plausibility`'s `distance_to_target_hospital_km` is not
  populated** in the current route wiring — it's computed in the scorer
  but the API layer doesn't yet pass it in. Low priority since
  `gps_telemetry_match` covers the more important version of this signal.

## Ambulance tracking

- **Distance/ETA shown to the patient is straight-line, not routed.**
  `DispatchTracking.jsx` computes haversine distance between the
  ambulance and patient, not a real road-network ETA. Real turn-by-turn
  routing requires a routing service (OSRM self-hosted, GraphHopper, or a
  paid provider like Mapbox/Google Directions) — not wired in, and
  intentionally not faked with an invented "12 minutes" figure.
- **No real ambulance-crew app.** `/dispatch/{id}/ambulance-location` is
  currently authorized for the `dispatcher` role, meaning fleet dispatch
  staff relay position from existing radio/GPS hardware, not a
  purpose-built driver app. Building that driver app (likely the same
  Capacitor pattern as the patient app, with a much simpler UI) is a
  real, scoped next project, not done here.

## Identity, abuse prevention & mobile

- **No web page or native app can read a phone's IMEI.** No modern mobile
  OS exposes it to apps, web or native, for privacy reasons — this is a
  platform constraint, not a gap in this codebase. The closest available
  signal is `@capacitor/device`'s per-install identifier on native
  builds (see `MOBILE_BUILDS.md`), or a localStorage UUID on web, both
  already wired into device-fingerprint-based abuse detection.
- **VoIP/burner-number detection (Twilio Lookup) and CAPTCHA are both
  real, working integrations but ship disabled by default** — they need
  your own Twilio/Turnstile account credentials in `.env` to activate.
- **Push notifications are scaffolded, not wired.**
  `@capacitor/push-notifications` is a dependency; there's no APNs/FCM
  backend integration yet (no server-side push-sending code, no device-
  token storage). A real next step, not attempted here.

## Payments / financial deterrence

- **No real payment processor is integrated.** The anti-prank spec calls
  for a "payment method on file" friction layer; `User.payment_method_
  on_file` exists as a boolean flag and the false-dispatch fee amount is
  configurable (`FALSE_DISPATCH_FEE_USD`), but there's no Stripe/PCI-
  compliant billing integration actually charging anyone. Wiring real
  billing requires a payment processor account and PCI-scope review this
  codebase can't do on your behalf.

## Security (see SECURITY.md for the full control-by-control breakdown)

Highlights not to miss: no WAF appliance, no mTLS service mesh, no
refresh-token rotation/denylist, no just-in-time privilege elevation, no
automated dependency scanning in CI, no documented incident-response
plan. All flagged explicitly in `SECURITY.md` rather than silently
omitted — that file is the canonical list.

## Cross-platform (web / iOS / Android)

- **iOS and Android are Capacitor-wrapped builds of the same React app**,
  not separate native rewrites — see `MOBILE_BUILDS.md` for exactly what
  that means, what native permission entries you must add by hand, and
  what still isn't done (real app-store assets, push backend, signing/CI).
- The dispatcher dashboard (`frontend-dispatcher/`) is web-only. Wrapping
  it the same way is possible but wasn't done — it's an internal tool for
  hospital staff at a desk, where mobile packaging is lower priority than
  for the patient-facing app.

## Testing

- **19 backend unit/integration tests exist** (triage engine, dispatch
  confidence scorer, facility-capability mapping) and were run against a
  real, live PostgreSQL+PostGIS instance during development — not just
  written and assumed to pass; two real bugs were caught and fixed this
  way (see git history / build notes). There are no frontend tests (React
  Testing Library / Playwright) yet, and no load/performance testing.
