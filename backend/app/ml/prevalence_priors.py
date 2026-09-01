"""
Epidemiological prior recalibration.

The training dataset (app/ml/data/) has an artificial uniform class
distribution — every disease has roughly the same number of rows,
regardless of how common that disease actually is (see
`audit_dataset.py`, which flags this automatically). A classifier trained
on it therefore implicitly assumes every disease is equally likely, which
is false and would bias triage output toward over-diagnosing rare
conditions relative to common ones.

This module corrects for that with a standard Bayesian technique: divide
out the (uniform, wrong) training prior and multiply in a real regional
prior, then renormalize. This does NOT touch the trained model or require
retraining — it's a post-hoc calibration layer applied to the model's
output probabilities.

    P_corrected(disease | symptoms) ∝ P_model(disease | symptoms)
                                       / P_train_prior(disease)
                                       * P_regional_prior(disease)

Data sources for the regional priors below (cited, not invented):
  - Malaria incidence, Kenya: ~63.65 cases per 1,000 population at risk
    (2021), WHO Global Health Observatory, via WHO/AFRO "Kenya Health
    Profile 2025" (afro.who.int).
  - Tuberculosis incidence, Kenya: 223 per 100,000 population (2023),
    WHO Global Tuberculosis Report 2024 / World Bank SH.TBS.INCD.
  - Diseases without a reliably sourced regional incidence figure are left
    at NEUTRAL (multiplier 1.0, i.e. no correction) rather than guessed —
    an unjustified prior is worse than no prior.

This is intentionally a small, explicit, per-region, human-editable table
— not a scraped or model-estimated one — so a clinician or public-health
partner can review, correct, or extend it before it affects real triage
output, and so it's obvious to any reader which numbers are sourced and
which are not.
"""
from __future__ import annotations

import numpy as np

# Approximate annual incidence proportion (cases per person per year) by
# region. `None` = no sourced figure available; treated as neutral.
REGIONAL_INCIDENCE: dict[str, dict[str, float | None]] = {
    "kenya": {
        "Malaria": 63.65 / 1000,       # WHO GHO via AFRO Kenya Health Profile 2025
        "Tuberculosis": 223 / 100_000,  # WHO Global TB Report 2024
        # Everything else: no sourced regional figure yet. Add entries here
        # as your public-health/hospital partners provide validated data,
        # citing the source inline the way the two rows above do.
    },
    # Add further region keys (e.g. "tanzania", "uganda", "national") the
    # same way, each with cited sources in a comment.
}

DEFAULT_REGION = "kenya"


def get_regional_prior_multiplier(disease: str, region: str = DEFAULT_REGION) -> float:
    """Returns a relative-likelihood multiplier, not an absolute probability."""
    table = REGIONAL_INCIDENCE.get(region, {})
    incidence = table.get(disease)
    return incidence if incidence is not None else 1.0


def recalibrate(
    proba: np.ndarray,
    labels: list[str],
    train_class_prior: dict[str, float],
    region: str = DEFAULT_REGION,
) -> np.ndarray:
    """
    Applies the Bayesian prior-swap described in the module docstring.
    `train_class_prior` should be the (uniform, dataset-artifact) prior
    computed in symptom_prevalence.json's "prior" key.
    """
    adjusted = np.zeros_like(proba)
    for i, disease in enumerate(labels):
        train_prior = max(train_class_prior.get(disease, 1.0 / len(labels)), 1e-9)
        regional_multiplier = get_regional_prior_multiplier(disease, region)
        adjusted[i] = proba[i] / train_prior * regional_multiplier

    total = adjusted.sum()
    if total <= 0:
        return proba  # degenerate — fall back to uncorrected output rather than divide by zero
    return adjusted / total
