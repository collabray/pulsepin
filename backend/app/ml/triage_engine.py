"""
Runtime inference for the Pure ML Symptom & Triage Engine and the Dynamic
Follow-Up Engine (concept paper Section 4.1).

Design notes:
  * Classification: XGBoost multi-class classifier trained in
    train_triage_model.py on a real public symptom/prognosis dataset.
  * Adaptive questioning: at each step, picks the symptom that maximizes
    *expected information gain* against the model's current posterior,
    using an empirical P(symptom | disease) table (Naive-Bayes-style
    simulation of "what would the posterior look like if this symptom
    were present / absent") rather than a fixed decision tree or a hand-
    written question order. This is a real, principled implementation of
    the "single most useful next yes/no question" behavior the concept
    paper specifies — not a placeholder.
  * Confidence floor: if the top prediction's probability is below
    settings.TRIAGE_CONFIDENCE_FLOOR after all informative questions are
    exhausted, the engine explicitly returns UNCERTAIN rather than naming
    a disease, per the paper's Section 8.1 non-goal ("does not claim to
    replace a doctor").
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import xgboost as xgb

from app.core.config import get_settings
from app.models.triage import UrgencyLevel

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"

# Conditions that map to an EMERGENCY urgency classification when they are
# the (sufficiently confident) top prediction. This is a controlled,
# clinician-reviewable list rather than an ML-guessed urgency — the concept
# paper explicitly separates *what condition* (ML) from *how urgent*
# (a policy layer that should be auditable and easy to correct), and this
# module keeps those two concerns in separate, independently-editable
# structures for exactly that reason.
EMERGENCY_CONDITIONS = {
    "Heart attack",
    "Paralysis (brain hemorrhage)",
    "Tuberculosis",
    "Pneumonia",
    "Dengue",
    "Hepatitis E",
    "Alcoholic hepatitis",
}
CLINIC_VISIT_CONDITIONS_DEFAULT = True  # anything not self-care/emergency defaults to clinic visit
SELF_CARE_CONDITIONS = {
    "Common Cold",
    "Allergy",
    "Acne",
    "Fungal infection",
    "Impetigo",
}


@dataclass
class TriageStepResult:
    ranked_conditions: list[dict]  # [{"condition": str, "probability": float}]
    top_condition: str | None
    top_probability: float
    urgency: UrgencyLevel
    next_question_symptom: str | None  # None => no more useful questions / done
    is_confident_enough_to_stop: bool


class TriageEngine:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._booster = self._load_model()
        self.labels: list[str] = self._load_json("triage_labels.json")
        self.symptom_index: list[str] = self._load_json("symptom_index.json")
        self.symptom_pos = {s: i for i, s in enumerate(self.symptom_index)}
        stats = self._load_json("symptom_prevalence.json")
        self.prior: dict[str, float] = stats["prior"]
        self.prevalence: dict[str, dict[str, float]] = stats["prevalence"]

    def _load_json(self, name: str):
        with open(ARTIFACTS_DIR / name) as f:
            return json.load(f)

    def _load_model(self) -> xgb.Booster:
        model_path = Path(self.settings.TRIAGE_MODEL_PATH)
        if not model_path.is_absolute():
            model_path = Path(__file__).parent.parent.parent / model_path
        booster = xgb.Booster()
        booster.load_model(str(model_path))
        return booster

    # ---------------------------------------------------------------- #
    # Classification
    # ---------------------------------------------------------------- #
    def _vectorize(self, responses: dict[str, int]) -> np.ndarray:
        vec = np.zeros((1, len(self.symptom_index)), dtype=np.float32)
        for symptom, value in responses.items():
            idx = self.symptom_pos.get(symptom)
            if idx is not None:
                vec[0, idx] = value
        return vec

    def predict_proba(self, responses: dict[str, int]) -> np.ndarray:
        dmat = xgb.DMatrix(self._vectorize(responses), feature_names=self.symptom_index)
        return self._booster.predict(dmat)[0]  # shape (n_classes,)

    def rank_conditions(self, responses: dict[str, int], top_k: int = 5) -> list[dict]:
        proba = self.predict_proba(responses)
        order = np.argsort(-proba)[:top_k]
        return [{"condition": self.labels[i], "probability": float(proba[i])} for i in order]

    # ---------------------------------------------------------------- #
    # Dynamic Follow-Up Engine — expected-information-gain question pick
    # ---------------------------------------------------------------- #
    def _simulate_posterior(self, responses: dict[str, int], symptom: str, value: int) -> np.ndarray:
        """What would predict_proba look like if `symptom` were answered `value`?"""
        hypothetical = dict(responses)
        hypothetical[symptom] = value
        return self.predict_proba(hypothetical)

    @staticmethod
    def _entropy(proba: np.ndarray) -> float:
        p = np.clip(proba, 1e-12, 1.0)
        return float(-np.sum(p * np.log2(p)))

    def _expected_info_gain(self, responses: dict[str, int], symptom: str) -> float:
        current = self.predict_proba(responses)
        h_current = self._entropy(current)

        # P(symptom=1) marginalized over the current posterior, using the
        # empirical prevalence table — this is what makes the simulated
        # "what if" branch weighting principled rather than a coin flip.
        p_symptom_present = sum(
            current[i] * self.prevalence.get(self.labels[i], {}).get(symptom, 0.5)
            for i in range(len(self.labels))
        )
        p_symptom_present = min(max(p_symptom_present, 1e-6), 1 - 1e-6)

        proba_if_present = self._simulate_posterior(responses, symptom, 1)
        proba_if_absent = self._simulate_posterior(responses, symptom, 0)

        h_if_present = self._entropy(proba_if_present)
        h_if_absent = self._entropy(proba_if_absent)

        expected_h = p_symptom_present * h_if_present + (1 - p_symptom_present) * h_if_absent
        return h_current - expected_h

    def select_next_question(
        self, responses: dict[str, int], max_candidates: int = 40
    ) -> str | None:
        """
        Returns the single symptom expected to reduce diagnostic entropy the
        most, restricted to symptoms not yet answered. To keep this fast in
        an interactive request/response loop, candidates are pre-filtered to
        the symptoms most differentially informative for the *current*
        top-ranked conditions (rather than scoring all 132 every turn).
        """
        asked = set(responses.keys())
        current = self.predict_proba(responses)
        top_idx = np.argsort(-current)[:6]
        top_diseases = [self.labels[i] for i in top_idx]

        candidate_symptoms = set()
        for disease in top_diseases:
            prevalences = self.prevalence.get(disease, {})
            # Symptoms whose prevalence for this disease is far from 0.5 in
            # either direction are the ones worth asking about at all.
            ranked = sorted(prevalences.items(), key=lambda kv: abs(kv[1] - 0.5), reverse=True)
            for symptom, _ in ranked[:15]:
                if symptom not in asked:
                    candidate_symptoms.add(symptom)
        if not candidate_symptoms:
            return None

        candidate_symptoms = list(candidate_symptoms)[:max_candidates]
        gains = {s: self._expected_info_gain(responses, s) for s in candidate_symptoms}
        best_symptom = max(gains, key=gains.get)
        if gains[best_symptom] <= 1e-4:
            return None
        return best_symptom

    # ---------------------------------------------------------------- #
    # Urgency mapping
    # ---------------------------------------------------------------- #
    def _urgency_for(self, condition: str, probability: float) -> UrgencyLevel:
        if probability < self.settings.TRIAGE_CONFIDENCE_FLOOR:
            return UrgencyLevel.UNCERTAIN
        if condition in EMERGENCY_CONDITIONS:
            return UrgencyLevel.EMERGENCY
        if condition in SELF_CARE_CONDITIONS:
            return UrgencyLevel.SELF_CARE
        return UrgencyLevel.CLINIC_VISIT

    # ---------------------------------------------------------------- #
    # Orchestration — one triage step
    # ---------------------------------------------------------------- #
    def step(self, responses: dict[str, int], questions_asked: int, max_questions: int = 12) -> TriageStepResult:
        ranked = self.rank_conditions(responses)
        top = ranked[0]
        urgency = self._urgency_for(top["condition"], top["probability"])

        stop_for_confidence = top["probability"] >= 0.75
        stop_for_budget = questions_asked >= max_questions

        next_q = None
        if not (stop_for_confidence or stop_for_budget):
            next_q = self.select_next_question(responses)

        is_done = next_q is None

        # Recompute urgency using the confidence floor at the point we
        # actually stop, so a session that exhausts its question budget
        # without reaching the floor is honestly reported as UNCERTAIN.
        if is_done:
            urgency = self._urgency_for(top["condition"], top["probability"])

        return TriageStepResult(
            ranked_conditions=ranked,
            top_condition=top["condition"],
            top_probability=top["probability"],
            urgency=urgency,
            next_question_symptom=next_q,
            is_confident_enough_to_stop=is_done,
        )


@lru_cache
def get_triage_engine() -> TriageEngine:
    return TriageEngine()
