"""
Runs against the actual trained artifacts in app/ml/artifacts/ (produced by
train_triage_model.py + build_symptom_stats.py) — these are integration
tests of the real model, not mocks of it.
"""
import pytest

from app.ml.triage_engine import get_triage_engine


@pytest.fixture(scope="module")
def engine():
    return get_triage_engine()


def test_engine_loads_labels_and_symptoms(engine):
    assert len(engine.labels) > 0
    assert len(engine.symptom_index) > 0
    assert "prognosis" not in engine.symptom_index  # label column must not leak into features


def test_empty_responses_produce_a_valid_distribution(engine):
    proba = engine.predict_proba({})
    assert abs(sum(proba) - 1.0) < 1e-4
    assert all(p >= 0 for p in proba)


def test_strong_symptom_pattern_increases_top_probability(engine):
    # Fungal infection's dominant pattern in the training data.
    baseline = engine.predict_proba({})
    responses = {"itching": 1, "skin_rash": 1, "nodal_skin_eruptions": 1, "dischromic _patches": 1}
    informed = engine.predict_proba(responses)
    baseline_top = max(baseline)
    informed_top = max(informed)
    assert informed_top >= baseline_top  # more evidence should not reduce confidence in the best guess


def test_select_next_question_returns_an_unasked_symptom(engine):
    responses = {"itching": 1}
    q = engine.select_next_question(responses)
    assert q is None or q not in responses


def test_step_respects_question_budget(engine):
    result = engine.step({}, questions_asked=0, max_questions=0)
    assert result.next_question_symptom is None
    assert result.is_confident_enough_to_stop is True


def test_urgency_uncertain_below_confidence_floor(engine):
    # No symptoms answered -> flat-ish distribution -> low top probability
    # for a 41-class problem -> should not claim a confident diagnosis.
    result = engine.step({}, questions_asked=999, max_questions=0)
    if result.top_probability < engine.settings.TRIAGE_CONFIDENCE_FLOOR:
        assert result.urgency.value == "uncertain"


def test_rank_conditions_is_sorted_descending(engine):
    ranked = engine.rank_conditions({"itching": 1, "skin_rash": 1})
    probs = [r["probability"] for r in ranked]
    assert probs == sorted(probs, reverse=True)
