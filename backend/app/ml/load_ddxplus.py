"""
Adapter to plug the real DDXPlus dataset into the existing training
pipeline (train_triage_model.py) as a drop-in, much larger replacement
for the small bootstrap dataset in app/ml/data/.

DDXPlus (Tchango et al., "DDXPlus: A New Dataset For Automatic Medical
Diagnosis", NeurIPS 2022 Datasets & Benchmarks track) is a large-scale
(~1.3M patients), clinically-modeled synthetic dataset covering 49
pathologies with 223 evidence types (binary, categorical, and
multi-choice), released under CC-BY 4.0 by Mila (a peer-reviewed academic
lab), built from a proprietary medical knowledge base and a commercial
rule-based diagnosis system. This is a materially better dataset than the
132-symptom bootstrap CSVs shipped in this repo — see LIMITATIONS.md for
exactly how they differ (this one is NOT class-balanced by construction,
i.e. it reflects a designed prevalence rather than an artificial uniform
split, and has far more distinct symptom patterns per condition).

WHY THIS FILE DOWNLOADS NOTHING ITSELF: DDXPlus's release files are
hosted on figshare, which was not a reachable domain from the sandboxed
environment this project was originally built in (see LIMITATIONS.md).
This module's parsing logic below is real and complete — written
directly from the dataset's documented schema (mila-iqia/ddxplus README
+ the original paper) — you only need to supply the actual files.

------------------------------------------------------------------------
SETUP
------------------------------------------------------------------------
1. Download from https://github.com/mila-iqia/ddxplus (README links to
   the actual figshare release) or the mirrored copy at
   https://huggingface.co/datasets/aai530-group6/ddxplus (English
   version; the original French-language release is a separate figshare
   entry linked from the same README — get the English one unless you
   specifically want French-language evidence text).
2. You need these 5 files:
     release_evidences.json
     release_conditions.json
     release_train_patients.csv   (may ship as release_train_patients.zip)
     release_validate_patients.csv
     release_test_patients.csv
3. Place all 5 under: app/ml/data/ddxplus/
4. Run: python -m app.ml.load_ddxplus --smoke-test
   This loads and validates the files without training anything, and
   prints dataset stats so you can sanity-check the download before a
   multi-minute training run.
5. Point train_triage_model.py at this loader — see
   TRAINING_WITH_LARGER_DATASETS.md at the repo root for the one-line
   change and, importantly, for what else in the codebase (condition ->
   urgency mapping, condition -> hospital-capability mapping) needs
   updating because DDXPlus's 49 pathologies are a different label set
   than the bootstrap dataset's 41.
------------------------------------------------------------------------

Binarization approach: DDXPlus evidences can be binary, categorical, or
multi-choice. To keep the existing training pipeline's (X: binary matrix,
y: label) shape unchanged, this loader binarizes every observed
(evidence_code, value) pair into its own 0/1 column — e.g. a categorical
pain-characteristic evidence with 5 possible values becomes 5 separate
binary columns, one per value. This preserves the information the
categorical/multi-choice evidences carry (nothing is thrown away by
collapsing "which value" into one generic "evidence present" column), at
the cost of a wider feature matrix (223 evidence types expand to several
hundred binarized columns) — XGBoost handles this width comfortably.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd

DDXPLUS_DIR = Path(__file__).parent / "data" / "ddxplus"

REQUIRED_FILES = [
    "release_evidences.json",
    "release_conditions.json",
    "release_train_patients.csv",
    "release_validate_patients.csv",
    "release_test_patients.csv",
]


def _check_files_present() -> None:
    missing = [f for f in REQUIRED_FILES if not (DDXPLUS_DIR / f).exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing DDXPlus files under {DDXPLUS_DIR}: {missing}. "
            "See this module's docstring for where to download them."
        )


def _parse_evidence_list(raw) -> list[str]:
    """
    The EVIDENCES column stores a Python-list-literal string, e.g.
    "['E_55', 'E_53_@_V_130', 'E_204_@_V_1']" — binary evidences appear as
    their bare code; categorical/multi-choice evidences appear suffixed
    with "_@_" + the specific value code that was observed.
    """
    if not raw or (isinstance(raw, float) and pd.isna(raw)):
        return []
    return ast.literal_eval(raw)


def _load_condition_name_map(conditions: dict) -> dict[str, str]:
    """condition_code -> human-readable condition_name, per release_conditions.json."""
    return {code: info.get("condition_name", code) for code, info in conditions.items()}


def load_ddxplus_dataset(
    split: str = "train", max_rows: int | None = None
) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """
    Returns (X, y, symptom_cols) in the same shape train_triage_model.py's
    load_dataset() returns, so it's a drop-in replacement.

    split: "train", "validate", or "test" — DDXPlus ships pre-split;
        train_triage_model.py's own train_test_split can still be applied
        on top of whichever split you load here, or load "train" for
        fitting and "test" as a final untouched holdout — your call
        depending on how you want to structure evaluation.
    max_rows: optional cap for a first smoke-test run before committing to
        loading the full ~1M-row training split, which takes real time
        and memory to binarize.
    """
    _check_files_present()

    with open(DDXPLUS_DIR / "release_conditions.json") as f:
        conditions = json.load(f)
    condition_names = _load_condition_name_map(conditions)

    csv_path = DDXPLUS_DIR / f"release_{split}_patients.csv"
    df = pd.read_csv(csv_path, nrows=max_rows)

    if "EVIDENCES" not in df.columns or "PATHOLOGY" not in df.columns:
        raise ValueError(
            f"{csv_path} doesn't have the expected DDXPlus columns "
            f"(found: {list(df.columns)}). Confirm you downloaded the "
            "English-language release, not a differently-shaped mirror."
        )

    df["_evidence_list"] = df["EVIDENCES"].apply(_parse_evidence_list)

    # Build the binarized vocabulary from the data actually observed
    # (rather than release_evidences.json's full catalog, which includes
    # evidence/value combinations that may never appear in a given split).
    all_columns: set[str] = set()
    for ev_list in df["_evidence_list"]:
        all_columns.update(ev_list)
    symptom_cols = sorted(all_columns)
    col_index = {c: i for i, c in enumerate(symptom_cols)}

    X_arr = np.zeros((len(df), len(symptom_cols)), dtype=np.int8)
    for row_i, ev_list in enumerate(df["_evidence_list"]):
        for ev in ev_list:
            X_arr[row_i, col_index[ev]] = 1

    X = pd.DataFrame(X_arr, columns=symptom_cols)
    y = df["PATHOLOGY"].map(lambda code: condition_names.get(code, code))

    return X, y, symptom_cols


def _smoke_test() -> None:
    _check_files_present()
    print(f"Found all required files under {DDXPLUS_DIR}.")

    X, y, symptom_cols = load_ddxplus_dataset(split="train", max_rows=5000)
    print(f"Loaded {len(X)} rows (capped at 5000 for the smoke test), "
          f"{len(symptom_cols)} binarized evidence columns, "
          f"{y.nunique()} distinct conditions.")
    print("Condition distribution (top 10):")
    print(y.value_counts().head(10))
    print(
        "\nThis was a capped smoke test. The full training split is ~1M "
        "rows — call load_ddxplus_dataset(split='train') with no max_rows "
        "for the real run, or see TRAINING_WITH_LARGER_DATASETS.md for a "
        "recommended stratified-subsample approach if the full split is "
        "more than your training environment can comfortably handle."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    if args.smoke_test:
        _smoke_test()
    else:
        print("Run with --smoke-test to validate your downloaded DDXPlus files. "
              "See this module's docstring for setup steps.")
