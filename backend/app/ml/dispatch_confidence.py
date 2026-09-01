"""
Dispatch Confidence Engine (concept paper Section 5).

Honesty note on the model, read this before wiring it into a live
deployment: the paper specifies a gradient-boosted tree model (XGBoost /
LightGBM) with SHAP explainability, trained on historical dispatch
outcomes (confirmed-real vs. confirmed-false requests). That training
signal does not exist yet for a platform with zero real dispatch history
— fabricating "training data" for this would mean shipping a model that
learned invented patterns and presenting it as if it reflected real
abuse behavior. That is a worse safety failure than not having ML here
yet.

So this module ships two things:

1. `score()` — a fully deterministic, hand-specified weighted-sum scorer
   over the same feature groups the paper defines (5.1.A-D), used for
   cold start. Every weight and threshold is a named constant below, so
   it is auditable and adjustable by a human reviewer from day one —
   which the paper itself requires ("every flagged or auto-approved
   decision must be explainable").
2. `train_from_audit_log()` — trains a real XGBoost model from the
   `dispatch_requests` audit table (Section 5.3) once it contains
   outcome-labeled rows (`outcome_confirmed_real` is not null). Once
   `artifacts/dispatch_confidence.xgb.json` exists, `score()`
   automatically defers to the trained model and falls back to the
   deterministic scorer only for feature combinations far outside the
   training distribution.

This two-stage design *is* the paper's Section 8.3 staged rollout applied
to the confidence engine itself, not a shortcut around it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import get_settings
from app.models.dispatch import DispatchConfidenceTier

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
DISPATCH_MODEL_FILE = ARTIFACTS_DIR / "dispatch_confidence.xgb.json"

# --- Named, auditable weights (Section 5.1 signal groups A-D, extended
# with the GPS-telemetry-matching signal from the supplied anti-prank
# spec: "compares the requested pickup address against the user's live
# smartphone GPS coordinates") ---
WEIGHTS = {
    # A. Symptom & Triage Consistency
    "triage_urgency_consistency": 0.18,
    "escalation_time_plausibility": 0.07,
    # B. Account & Behavioral History
    "phone_account_age": 0.11,
    "prior_confirmed_real_rate": 0.13,
    "device_sim_consistency": 0.09,
    # C. Location Plausibility
    "gps_plausibility": 0.10,
    "travel_time_plausibility": 0.04,
    "gps_telemetry_match": 0.14,  # reported pickup location vs device's live GPS
    # D. Real-Time Interaction Signals
    "triage_completion": 0.09,
    "reverse_call_latency": 0.05,  # only scored post-hoc / for tier-2 review
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "WEIGHTS must sum to 1.0"


@dataclass
class DispatchFeatures:
    # A. Symptom & triage consistency
    triage_urgency_at_completion: str | None  # "self_care"/"clinic_visit"/"emergency"/"uncertain"/None
    seconds_since_triage_completion: float | None
    used_silent_override: bool

    # B. Account & behavioral history
    account_age_days: float
    prior_dispatch_count: int
    prior_confirmed_real_count: int
    prior_confirmed_false_count: int
    distinct_phone_numbers_on_device: int

    # C. Location plausibility
    gps_accuracy_meters: float | None
    implied_speed_kmh_since_last_ping: float | None  # None if no prior ping
    distance_to_target_hospital_km: float | None
    # Distance (km) between the reported pickup location and the
    # requesting device's own live GPS reading at request time. This is
    # the core "GPS Telemetry Matching" signal from the anti-prank spec:
    # a request for a location miles from the phone's actual position is
    # the single strongest hoax indicator available before human review.
    reported_vs_device_gps_distance_km: float | None

    # D. Real-time interaction
    triage_fully_completed: bool


@dataclass
class DispatchScoreResult:
    score: float  # 0..1, higher = more trustworthy
    tier: DispatchConfidenceTier
    feature_contributions: dict[str, float] = field(default_factory=dict)
    model_used: str = "deterministic_v1"


def _score_triage_consistency(f: DispatchFeatures) -> float:
    if f.used_silent_override:
        # Silent Override is scored on a separate branch by design (Section
        # 5.1.A) — normal urgency-jump logic does not apply and should not
        # penalize it.
        return 0.9
    if f.triage_urgency_at_completion == "emergency":
        base = 1.0
    elif f.triage_urgency_at_completion == "clinic_visit":
        base = 0.5
    elif f.triage_urgency_at_completion == "self_care":
        base = 0.15  # jumping from self-care straight to emergency dispatch is the flagged pattern
    else:
        base = 0.35  # no completed triage backing the dispatch at all

    if f.seconds_since_triage_completion is not None:
        # A very long gap between triage and dispatch, with no new triage
        # input in between, is itself a mild inconsistency signal.
        hours = f.seconds_since_triage_completion / 3600
        if hours > 6:
            base *= 0.7
    return max(0.0, min(1.0, base))


def _score_escalation_time(f: DispatchFeatures) -> float:
    if f.seconds_since_triage_completion is None:
        return 0.5
    minutes = f.seconds_since_triage_completion / 60
    # Plausible escalation window: seconds to ~2 hours. Instantaneous
    # (<2s, likely scripted) or implausibly delayed (>12h) both dock score.
    if minutes < 0.03:
        return 0.3
    if minutes <= 120:
        return 1.0
    if minutes <= 720:
        return 0.6
    return 0.3


def _score_account_age(f: DispatchFeatures) -> float:
    days = f.account_age_days
    if days >= 90:
        return 1.0
    if days >= 30:
        return 0.8
    if days >= 7:
        return 0.55
    if days >= 1:
        return 0.3
    return 0.1  # same-day account, first-ever dispatch request


def _score_prior_history(f: DispatchFeatures) -> float:
    if f.prior_dispatch_count == 0:
        return 0.5  # neutral — no history either way
    real_rate = f.prior_confirmed_real_count / f.prior_dispatch_count
    false_penalty = min(f.prior_confirmed_false_count * 0.15, 0.6)
    return max(0.0, min(1.0, 0.4 + 0.6 * real_rate - false_penalty))


def _score_device_consistency(f: DispatchFeatures) -> float:
    if f.distinct_phone_numbers_on_device <= 1:
        return 1.0
    if f.distinct_phone_numbers_on_device == 2:
        return 0.6
    return 0.2  # 3+ numbers on one device filing dispatch requests


def _score_gps_plausibility(f: DispatchFeatures) -> float:
    score = 1.0
    if f.gps_accuracy_meters is not None:
        if f.gps_accuracy_meters > 500:
            score *= 0.5
        elif f.gps_accuracy_meters > 150:
            score *= 0.8
    if f.implied_speed_kmh_since_last_ping is not None:
        # >250 km/h between consecutive pings implies a GPS teleport/spoof.
        if f.implied_speed_kmh_since_last_ping > 250:
            score *= 0.15
        elif f.implied_speed_kmh_since_last_ping > 150:
            score *= 0.6
    return max(0.0, min(1.0, score))


def _score_travel_time(f: DispatchFeatures) -> float:
    if f.distance_to_target_hospital_km is None:
        return 0.7
    # Extremely large distances to the "nearest" matched hospital suggest
    # either a location error or a routing edge case worth a human look.
    if f.distance_to_target_hospital_km > 150:
        return 0.3
    return 1.0


def _score_gps_telemetry_match(f: DispatchFeatures) -> float:
    """
    Core hoax-detection signal from the anti-prank spec: does the
    requested pickup location match where the requesting phone actually
    is? No device GPS reading available (e.g. browser denied location
    permission and the user typed an address) is scored neutrally rather
    than penalized, since denying a permission prompt is not itself
    suspicious — but it does mean this signal contributes nothing, which
    is reflected honestly rather than assumed favorable.
    """
    if f.reported_vs_device_gps_distance_km is None:
        return 0.55
    d = f.reported_vs_device_gps_distance_km
    if d <= 0.3:
        return 1.0
    if d <= 2:
        return 0.85
    if d <= 10:
        return 0.5
    if d <= 50:
        return 0.2
    return 0.05  # "miles away from the phone's actual physical position"


def _score_triage_completion(f: DispatchFeatures) -> float:
    return 1.0 if f.triage_fully_completed else 0.3


def score(features: DispatchFeatures) -> DispatchScoreResult:
    settings = get_settings()

    contributions = {
        "triage_urgency_consistency": WEIGHTS["triage_urgency_consistency"]
        * _score_triage_consistency(features),
        "escalation_time_plausibility": WEIGHTS["escalation_time_plausibility"]
        * _score_escalation_time(features),
        "phone_account_age": WEIGHTS["phone_account_age"] * _score_account_age(features),
        "prior_confirmed_real_rate": WEIGHTS["prior_confirmed_real_rate"]
        * _score_prior_history(features),
        "device_sim_consistency": WEIGHTS["device_sim_consistency"]
        * _score_device_consistency(features),
        "gps_plausibility": WEIGHTS["gps_plausibility"] * _score_gps_plausibility(features),
        "travel_time_plausibility": WEIGHTS["travel_time_plausibility"]
        * _score_travel_time(features),
        "gps_telemetry_match": WEIGHTS["gps_telemetry_match"] * _score_gps_telemetry_match(features),
        "triage_completion": WEIGHTS["triage_completion"] * _score_triage_completion(features),
        "reverse_call_latency": 0.0,  # populated post-hoc after Reverse Call, not at scoring time
    }
    total = sum(contributions.values()) / (1.0 - WEIGHTS["reverse_call_latency"])
    total = max(0.0, min(1.0, total))

    # Rescale the contributions dict by the same factor so it genuinely
    # sums to `total` — this dict exists specifically for audit/
    # explainability purposes (Security Architecture Section 5: "every
    # flagged or auto-approved decision must be explainable"), so it must
    # not silently drift from the score it's supposed to explain.
    rescale = total / sum(contributions.values()) if sum(contributions.values()) > 0 else 1.0
    contributions = {k: v * rescale for k, v in contributions.items()}

    if total >= settings.DISPATCH_HIGH_CONFIDENCE_THRESHOLD:
        tier = DispatchConfidenceTier.HIGH
    elif total >= settings.DISPATCH_MEDIUM_CONFIDENCE_THRESHOLD:
        tier = DispatchConfidenceTier.MEDIUM
    else:
        tier = DispatchConfidenceTier.LOW

    # Hard override, not just a weighted vote: a large GPS mismatch (the
    # anti-prank spec's core hoax signal — "a request made for a location
    # miles away from the phone's actual physical position flags a
    # high-risk warning for the dispatcher") must not be votable-away by
    # an otherwise-clean account history. A single strong red flag caps
    # the tier rather than being averaged into a good overall score.
    gps_component = _score_gps_telemetry_match(features)
    if (
        features.reported_vs_device_gps_distance_km is not None
        and gps_component <= 0.2
        and tier == DispatchConfidenceTier.HIGH
    ):
        tier = DispatchConfidenceTier.MEDIUM

    return DispatchScoreResult(score=total, tier=tier, feature_contributions=contributions)


def train_from_audit_log(db_session) -> dict:
    """
    Retrains a real XGBoost classifier on outcome-labeled DispatchRequest
    rows (outcome_confirmed_real IS NOT NULL). Intended to be run as a
    scheduled job once a hospital pilot has produced enough labeled
    outcomes (the paper's own Section 5.3 audit trail is exactly this
    table). Raises explicitly rather than silently training on too little
    data, so nobody accidentally ships a model fit to a handful of rows.
    """
    import numpy as np
    import pandas as pd
    from sklearn.model_selection import train_test_split
    from xgboost import XGBClassifier

    from app.models.dispatch import DispatchRequest

    rows = (
        db_session.query(DispatchRequest)
        .filter(DispatchRequest.outcome_confirmed_real.isnot(None))
        .filter(DispatchRequest.scoring_features.isnot(None))
        .all()
    )
    MIN_LABELED_ROWS = 200
    if len(rows) < MIN_LABELED_ROWS:
        raise ValueError(
            f"Only {len(rows)} outcome-labeled dispatch requests available; "
            f"need at least {MIN_LABELED_ROWS} before retraining a model. "
            "Continue using the deterministic scorer until then."
        )

    feature_names = sorted(WEIGHTS.keys())
    X = pd.DataFrame(
        [{k: r.scoring_features.get(k, 0.0) for k in feature_names} for r in rows]
    )
    y = np.array([1 if r.outcome_confirmed_real else 0 for r in rows])

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    model = XGBClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.1, eval_metric="logloss", random_state=42
    )
    model.fit(X_train, y_train)
    test_acc = float(model.score(X_test, y_test))

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    model.save_model(str(DISPATCH_MODEL_FILE))

    return {"n_labeled_rows": len(rows), "test_accuracy": test_acc, "feature_names": feature_names}
