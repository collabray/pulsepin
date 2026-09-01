"""
Trains the Pure ML Symptom & Triage Engine (concept paper Section 4.1).

Data source: a public 132-symptom / 41-disease dataset (binary symptom
indicators -> prognosis), mirrored at
https://raw.githubusercontent.com/anujdutt9/Disease-Prediction-from-Symptoms/master/dataset/
which itself derives from the Columbia University DiseaseSymptomKB and the
"Disease Prediction Using Machine Learning" Kaggle dataset. It is checked
into this repo under app/ml/data/ so training is fully reproducible offline.

This is real, labeled, publicly-sourced training data — not synthetic or
mock data. It is small and geographically non-specific, which is a real
limitation, not a hidden one: see LIMITATIONS.md for what that means for
production use and how the model is designed to be retrained on
hospital-partner data as it becomes available (Phase 1 -> Phase 2 handoff
in the roadmap).

Usage:
    python -m app.ml.train_triage_model
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    f1_score,
    log_loss,
    top_k_accuracy_score,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

DATA_DIR = Path(__file__).parent / "data"
ARTIFACTS_DIR = Path(__file__).parent / "artifacts"


def load_dataset() -> tuple[pd.DataFrame, pd.Series, list[str]]:
    train_df = pd.read_csv(DATA_DIR / "training_data.csv")
    test_df = pd.read_csv(DATA_DIR / "test_data.csv")

    # Both files ship with a trailing unnamed empty column — drop any
    # fully-null / unnamed columns rather than hardcoding a column count.
    for df in (train_df, test_df):
        df.drop(columns=[c for c in df.columns if c.startswith("Unnamed") or df[c].isna().all()],
                 inplace=True, errors="ignore")

    full = pd.concat([train_df, test_df], ignore_index=True).drop_duplicates()
    full["prognosis"] = full["prognosis"].str.strip()

    symptom_cols = [c for c in full.columns if c != "prognosis"]
    X = full[symptom_cols].astype(int)
    y = full["prognosis"]
    return X, y, symptom_cols


def main() -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    X, y, symptom_cols = load_dataset()
    print(f"Loaded {len(X)} labeled records, {len(symptom_cols)} symptoms, "
          f"{y.nunique()} distinct conditions.")

    label_encoder = LabelEncoder()
    y_enc = label_encoder.fit_transform(y)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y_enc, test_size=0.2, random_state=42, stratify=y_enc
    )

    model = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.08,
        subsample=0.85,
        colsample_bytree=0.85,
        objective="multi:softprob",
        eval_metric="mlogloss",
        num_class=len(label_encoder.classes_),
        n_jobs=-1,
        random_state=42,
    )

    # 5-fold stratified cross-validation on the training split for an
    # honest generalization estimate, in addition to the held-out test set.
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = []
    for fold, (tr_idx, val_idx) in enumerate(skf.split(X_train, y_train), start=1):
        fold_model = XGBClassifier(**model.get_params())
        fold_model.fit(X_train.iloc[tr_idx], y_train[tr_idx])
        preds = fold_model.predict(X_train.iloc[val_idx])
        acc = accuracy_score(y_train[val_idx], preds)
        cv_scores.append(acc)
        print(f"  fold {fold}: accuracy={acc:.4f}")
    print(f"CV accuracy: mean={np.mean(cv_scores):.4f} std={np.std(cv_scores):.4f}")

    model.fit(X_train, y_train)

    test_pred = model.predict(X_test)
    test_proba = model.predict_proba(X_test)

    metrics = {
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "n_classes": int(len(label_encoder.classes_)),
        "n_symptoms": int(len(symptom_cols)),
        "cv_accuracy_mean": float(np.mean(cv_scores)),
        "cv_accuracy_std": float(np.std(cv_scores)),
        "test_accuracy": float(accuracy_score(y_test, test_pred)),
        "test_top3_accuracy": float(
            top_k_accuracy_score(y_test, test_proba, k=3, labels=range(len(label_encoder.classes_)))
        ),
        "test_macro_f1": float(f1_score(y_test, test_pred, average="macro")),
        "test_log_loss": float(log_loss(y_test, test_proba, labels=range(len(label_encoder.classes_)))),
    }
    print(json.dumps(metrics, indent=2))
    print(classification_report(y_test, test_pred, target_names=label_encoder.classes_, zero_division=0))

    # Refit on 100% of available labeled data for the shipped artifact —
    # standard practice once cross-validated performance has been recorded,
    # since every held-out row is otherwise thrown away in a dataset this
    # small (4,920 rows across 41 classes).
    final_model = XGBClassifier(**model.get_params())
    final_model.fit(X, y_enc)

    # --- Export artifacts ---
    try:
        from onnxmltools import convert_xgboost
        from onnxmltools.convert.common.data_types import FloatTensorType

        onnx_model = convert_xgboost(
            final_model, initial_types=[("input", FloatTensorType([None, len(symptom_cols)]))]
        )
        with open(ARTIFACTS_DIR / "triage_model.onnx", "wb") as f:
            f.write(onnx_model.SerializeToString())
        print("Wrote ONNX model.")
    except ImportError:
        print("onnxmltools not installed — falling back to native XGBoost JSON artifact.", file=sys.stderr)
        final_model.save_model(str(ARTIFACTS_DIR / "triage_model.xgb.json"))

    with open(ARTIFACTS_DIR / "triage_labels.json", "w") as f:
        json.dump(list(label_encoder.classes_), f, indent=2)

    with open(ARTIFACTS_DIR / "symptom_index.json", "w") as f:
        json.dump(symptom_cols, f, indent=2)

    with open(ARTIFACTS_DIR / "training_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"Artifacts written to {ARTIFACTS_DIR}")


if __name__ == "__main__":
    main()
