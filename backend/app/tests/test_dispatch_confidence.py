from app.ml.dispatch_confidence import DispatchFeatures, WEIGHTS, score
from app.models.dispatch import DispatchConfidenceTier


def _base_features(**overrides) -> DispatchFeatures:
    defaults = dict(
        triage_urgency_at_completion="emergency",
        seconds_since_triage_completion=120,
        used_silent_override=False,
        account_age_days=180,
        prior_dispatch_count=1,
        prior_confirmed_real_count=1,
        prior_confirmed_false_count=0,
        distinct_phone_numbers_on_device=1,
        gps_accuracy_meters=20,
        implied_speed_kmh_since_last_ping=None,
        distance_to_target_hospital_km=5,
        reported_vs_device_gps_distance_km=0.1,
        triage_fully_completed=True,
    )
    defaults.update(overrides)
    return DispatchFeatures(**defaults)


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_strong_legitimate_request_scores_high():
    result = score(_base_features())
    assert result.tier == DispatchConfidenceTier.HIGH
    assert 0.0 <= result.score <= 1.0


def test_brand_new_account_self_care_jump_scores_lower():
    suspicious = _base_features(
        triage_urgency_at_completion="self_care",
        account_age_days=0.1,
        prior_dispatch_count=0,
        prior_confirmed_real_count=0,
        prior_confirmed_false_count=0,
        reported_vs_device_gps_distance_km=None,
    )
    legit = _base_features()
    assert score(suspicious).score < score(legit).score


def test_gps_mismatch_lowers_score():
    matched = _base_features(reported_vs_device_gps_distance_km=0.1)
    mismatched = _base_features(reported_vs_device_gps_distance_km=80)
    assert score(mismatched).score < score(matched).score
    assert score(mismatched).tier != DispatchConfidenceTier.HIGH


def test_repeated_false_history_penalized():
    clean = _base_features(prior_dispatch_count=5, prior_confirmed_real_count=5, prior_confirmed_false_count=0)
    history_of_false = _base_features(prior_dispatch_count=5, prior_confirmed_real_count=1, prior_confirmed_false_count=4)
    assert score(history_of_false).score < score(clean).score


def test_silent_override_does_not_get_penalized_for_urgency_jump():
    # Silent Override is deliberately scored on a separate branch — using
    # it should not be treated the same as an inconsistent triage jump.
    result = score(_base_features(used_silent_override=True, triage_urgency_at_completion=None))
    assert result.score > 0.3


def test_low_tier_for_many_red_flags():
    bad = _base_features(
        triage_urgency_at_completion="self_care",
        account_age_days=0.01,
        prior_dispatch_count=3,
        prior_confirmed_real_count=0,
        prior_confirmed_false_count=3,
        distinct_phone_numbers_on_device=4,
        reported_vs_device_gps_distance_km=100,
        triage_fully_completed=False,
    )
    result = score(bad)
    assert result.tier == DispatchConfidenceTier.LOW


def test_feature_contributions_sum_to_score():
    result = score(_base_features())
    assert abs(sum(result.feature_contributions.values()) - result.score) < 1e-6
