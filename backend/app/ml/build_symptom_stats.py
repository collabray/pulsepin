"""
Builds the empirical symptom-prevalence-per-disease table used by the
Dynamic Follow-Up Engine's information-gain question selection (concept
paper Section 4.1). Applies Laplace (add-one) smoothing so a symptom that
never/always co-occurs with a disease in a small training set doesn't
collapse a probability to exactly 0 or 1, which would make information-gain
math (log of zero) blow up and would overstate certainty on a small dataset.

IMPORTANT: this must be run against the SAME data source you trained the
classifier on (train_triage_model.py). The prevalence table and the
trained model are a matched pair — question selection in triage_engine.py
uses this table to simulate "what would the model's posterior look like
if this symptom were answered yes/no," which only makes sense if the
prevalence numbers came from the same data distribution the model itself
was fit on. Mismatching them (e.g. training on DDXPlus but building
stats from the bootstrap CSVs) will silently produce nonsensical question
selection — no error, just bad questions.

Usage:
    python -m app.ml.build_symptom_stats
    python -m app.ml.build_symptom_stats --data-source ddxplus
    python -m app.ml.build_symptom_stats --data-source custom --custom-csv-dir /path
"""
import argparse
import json
from pathlib import Path

from app.ml.train_triage_model import get_dataset

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-source", choices=["bootstrap", "ddxplus", "custom"], default="bootstrap")
    parser.add_argument("--custom-csv-dir", default=None)
    parser.add_argument("--ddxplus-max-rows", type=int, default=None)
    args = parser.parse_args()

    X, y, symptom_cols = get_dataset(args)
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
          f"{len(symptom_cols)} symptoms (data source: {args.data_source}).")


if __name__ == "__main__":
    main()
