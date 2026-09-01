"""
Builds the empirical symptom-prevalence-per-disease table used by the
Dynamic Follow-Up Engine's information-gain question selection (concept
paper Section 4.1). Applies Laplace (add-one) smoothing so a symptom that
never/always co-occurs with a disease in the small training set doesn't
collapse a probability to exactly 0 or 1, which would make information-gain
math (log of zero) blow up and would overstate certainty on a 305-row
dataset.

Usage:
    python -m app.ml.build_symptom_stats
"""
import json
from pathlib import Path

import pandas as pd

from app.ml.train_triage_model import load_dataset

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"


def main() -> None:
    X, y, symptom_cols = load_dataset()
    df = X.copy()
    df["prognosis"] = y.values

    diseases = sorted(df["prognosis"].unique())
    prior = {d: float((df["prognosis"] == d).mean()) for d in diseases}

    # P(symptom=1 | disease), Laplace-smoothed with alpha=1, 2 outcomes.
    prevalence: dict[str, dict[str, float]] = {}
    for disease in diseases:
        sub = df[df["prognosis"] == disease]
        n = len(sub)
        prevalence[disease] = {
            s: float((sub[s].sum() + 1) / (n + 2)) for s in symptom_cols
        }

    with open(ARTIFACTS_DIR / "symptom_prevalence.json", "w") as f:
        json.dump({"prior": prior, "prevalence": prevalence}, f, indent=2)

    print(f"Wrote symptom prevalence table for {len(diseases)} diseases, "
          f"{len(symptom_cols)} symptoms.")


if __name__ == "__main__":
    main()
