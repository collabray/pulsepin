"""
Prints an honest data-quality / bias report for whatever dataset is
currently wired into training. Run this before trusting any accuracy
number the training script prints, and re-run it any time the dataset is
swapped (e.g. after plugging in DDXPlus via load_ddxplus.py).

Usage:
    python -m app.ml.audit_dataset
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

    n_total = len(df)
    n_unique = len(df.drop_duplicates())
    dup_ratio = 1 - (n_unique / n_total) if n_total else 0

    per_class = df["prognosis"].value_counts()
    class_balance_cv = float(per_class.std() / per_class.mean()) if per_class.mean() else 0

    unique_patterns_per_class = df.drop_duplicates().groupby("prognosis").size()

    report = {
        "n_rows_total": int(n_total),
        "n_rows_unique": int(n_unique),
        "duplicate_row_ratio": round(dup_ratio, 4),
        "n_classes": int(df["prognosis"].nunique()),
        "n_symptoms": int(len(symptom_cols)),
        "rows_per_class_min": int(per_class.min()),
        "rows_per_class_max": int(per_class.max()),
        "class_balance_coefficient_of_variation": round(class_balance_cv, 4),
        "unique_symptom_patterns_per_class_mean": round(float(unique_patterns_per_class.mean()), 2),
        "unique_symptom_patterns_per_class_min": int(unique_patterns_per_class.min()),
        "warnings": [],
    }

    if dup_ratio > 0.5:
        report["warnings"].append(
            f"{dup_ratio:.0%} of rows are exact duplicates. The dataset behaves like a small set of "
            "fixed symptom templates repeated many times, not independent patient samples. Treat "
            "reported accuracy as an upper bound on real-world performance, not an estimate of it."
        )
    if class_balance_cv < 0.05:
        report["warnings"].append(
            "Classes are near-perfectly balanced (every disease has almost exactly the same row "
            "count). Real-world disease incidence is NOT uniform — this dataset does not reflect "
            "true prevalence and must not be used to estimate real-world base rates. See "
            "app/ml/prevalence_priors.py for the epidemiological-prior recalibration layer that "
            "compensates for this at inference time."
        )
    if unique_patterns_per_class.mean() < 20:
        report["warnings"].append(
            f"Only ~{unique_patterns_per_class.mean():.0f} distinct symptom patterns per disease on "
            "average. This is characteristic of a textbook/checklist-style dataset rather than "
            "messy real clinical presentations, and will understate the ambiguity real patients "
            "present with. Do not deploy against real patients without retraining on a larger, "
            "more clinically representative dataset (see app/ml/load_ddxplus.py)."
        )

    print(json.dumps(report, indent=2))
    with open(ARTIFACTS_DIR / "data_quality_report.json", "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
