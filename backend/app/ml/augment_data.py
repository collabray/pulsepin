"""
Synthetic data augmentation for the small bootstrap symptom dataset.

READ THIS BEFORE USING: augmentation techniques below (SMOTE and random
symptom-flip noise injection) do not add new real-world information. They
cannot fix the underlying problem `audit_dataset.py` flags — that the
bootstrap dataset only has ~7 distinct real symptom patterns per disease.
What they legitimately CAN do:

  1. Reduce overfitting to those exact patterns by training on
     interpolated/perturbed variants, which tends to produce smoother
     decision boundaries and better-calibrated (if not more accurate)
     probability estimates.
  2. Let you train with `class_weight`-style balancing without a model
     that's ever seen a single real example of a rare pattern.

What it can't do: teach the model a real symptom co-occurrence pattern
that isn't already implicit in the ~305 real rows. If your goal is
actually better accuracy on real patients, the honest path is more real
data (DDXPlus — see load_ddxplus.py — or a hospital partner's real triage
records once your pilot collects them), not more synthetic variants of
the same small dataset. Use this module as a stopgap, not a substitute
for that.

Usage:
    from app.ml.augment_data import augment_with_smote
    X_aug, y_aug = augment_with_smote(X, y)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def augment_with_smote(
    X: pd.DataFrame, y: pd.Series, k_neighbors: int = 3, random_state: int = 42
) -> tuple[pd.DataFrame, pd.Series]:
    """
    SMOTE (Synthetic Minority Oversampling Technique) generates synthetic
    rows by interpolating between real minority-class neighbors, rather
    than just duplicating them — meaningfully better than naive
    oversampling for binary/discretized features like these, though
    still bounded by the diversity of the real rows it interpolates
    between.

    k_neighbors must be less than the smallest class's sample count;
    this dataset's smallest class has ~5 rows, so the default (3) is
    deliberately conservative — raise it only if you've verified (via
    `python -m app.ml.audit_dataset`) that every class has enough rows.
    """
    from imblearn.over_sampling import SMOTE

    class_counts = y.value_counts()
    min_class_size = class_counts.min()
    effective_k = min(k_neighbors, min_class_size - 1)
    if effective_k < 1:
        raise ValueError(
            f"Smallest class has only {min_class_size} row(s) — SMOTE needs at least "
            "2 per class to interpolate. Consider random_flip_augment() instead, or "
            "gather at least 2 real examples of that condition first."
        )

    smote = SMOTE(k_neighbors=effective_k, random_state=random_state)
    X_res, y_res = smote.fit_resample(X, y)

    # SMOTE interpolates continuously between 0/1 features, producing
    # fractional values (e.g. 0.6) that don't correspond to a real
    # "symptom present" signal. Round back to binary so downstream code
    # (which assumes 0/1 symptom columns throughout the app, e.g.
    # triage_engine.py's vectorization) keeps working unchanged.
    X_res = pd.DataFrame(np.round(X_res).astype(int), columns=X.columns)
    return X_res, pd.Series(y_res, name=y.name)


def random_flip_augment(
    X: pd.DataFrame, y: pd.Series, multiplier: int = 3, flip_prob: float = 0.05, random_state: int = 42
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Simpler alternative to SMOTE: duplicates every real row `multiplier`
    times, randomly flipping each symptom bit with probability
    `flip_prob` per duplicate. This models "real patients present almost
    but not exactly like the textbook pattern" — a reasonable prior for
    small textbook-style datasets — without SMOTE's per-class minimum
    sample-count constraint, so it works even for a class with only 1 row.

    flip_prob is deliberately small by default: too high and you're
    training the model to associate essentially random symptom noise
    with a diagnosis, which actively hurts real accuracy rather than
    just failing to help it.
    """
    rng = np.random.default_rng(random_state)
    X_np = X.to_numpy()

    rows, labels = [], []
    for _ in range(multiplier):
        flips = rng.random(X_np.shape) < flip_prob
        flipped = np.where(flips, 1 - X_np, X_np)
        rows.append(flipped)
        labels.append(y.to_numpy())

    X_aug = np.vstack([X_np] + rows)
    y_aug = np.concatenate([y.to_numpy()] + labels)

    return pd.DataFrame(X_aug, columns=X.columns), pd.Series(y_aug, name=y.name)
