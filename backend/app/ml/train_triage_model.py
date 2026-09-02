"""
Trains the Pure ML Symptom & Triage Engine (concept paper Section 4.1).

Default data source: a public 132-symptom / 41-disease dataset (binary
symptom indicators -> prognosis), mirrored at
https://raw.githubusercontent.com/anujdutt9/Disease-Prediction-from-Symptoms/master/dataset/
which itself derives from the Columbia University DiseaseSymptomKB and the
"Disease Prediction Using Machine Learning" Kaggle dataset. It is checked
into this repo under app/ml/data/ so training is fully reproducible offline.

This is real, labeled, publicly-sourced training data — not synthetic or
mock data. It is small and geographically non-specific, which is a real
limitation, not a hidden one: see LIMITATIONS.md and
TRAINING_WITH_LARGER_DATASETS.md for what that means and for how to plug
in a larger dataset (DDXPlus via load_ddxplus.py) or your own data.

Usage:
    python -m app.ml.train_triage_model
    python -m app.ml.train_triage_model --data-source ddxplus
    python -m app.ml.train_triage_model --augment smote
    python -m app.ml.train_triage_model --class-weight --hyperparam-search
    python -m app.ml.train_triage_model --data-source custom --custom-csv-dir /path/to/dir

See TRAINING_WITH_LARGER_DATASETS.md at the repo root for a full guide to
every flag below and when to use which.
"""
from __future__ import annotations

import argparse
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
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold, train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

DATA_DIR = Path(__file__).parent / "data"
ARTIFACTS_DIR = Path(__file__).parent / "artifacts"


def load_dataset() -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """The original small bootstrap dataset (default data source)."""
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


def load_custom_csv_dataset(csv_dir: Path) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """
    Loads any CSV(s) shaped like the bootstrap dataset: binary 0/1 symptom
    columns plus a `prognosis` label column. Concatenates every *.csv file
    found directly under csv_dir (not recursive) — e.g. your own hospital
    partner's historical triage records, once exported to this shape.
    """
    csv_files = sorted(csv_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found under {csv_dir}.")

    frames = []
    for f in csv_files:
        df = pd.read_csv(f)
        if "prognosis" not in df.columns:
            raise ValueError(
                f"{f} has no 'prognosis' column. Every CSV must have a 'prognosis' "
                "label column plus 0/1 symptom columns, matching the bootstrap "
                "dataset's shape — reshape your export before pointing training here."
            )
        df.drop(columns=[c for c in df.columns if c.startswith("Unnamed") or df[c].isna().all()],
                 inplace=True, errors="ignore")
        frames.append(df)

    full = pd.concat(frames, ignore_index=True).drop_duplicates()
    full["prognosis"] = full["prognosis"].astype(str).str.strip()
    symptom_cols = [c for c in full.columns if c != "prognosis"]
    X = full[symptom_cols].fillna(0).astype(int)
    y = full["prognosis"]
    return X, y, symptom_cols


def get_dataset(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    if args.data_source == "bootstrap":
        return load_dataset()
    if args.data_source == "ddxplus":
        from app.ml.load_ddxplus import load_ddxplus_dataset

        return load_ddxplus_dataset(split="train", max_rows=args.ddxplus_max_rows)
    if args.data_source == "custom":
        if not args.custom_csv_dir:
            raise ValueError("--data-source custom requires --custom-csv-dir")
        return load_custom_csv_dataset(Path(args.custom_csv_dir))
    raise ValueError(f"Unknown data source: {args.data_source}")


def apply_augmentation(X: pd.DataFrame, y: pd.Series, method: str) -> tuple[pd.DataFrame, pd.Series]:
    if method == "none":
        return X, y
    from app.ml.augment_data import augment_with_smote, random_flip_augment

    if method == "smote":
        print("Applying SMOTE augmentation — see app/ml/augment_data.py's docstring: "
              "this improves training robustness, it does not add new real information.")
        return augment_with_smote(X, y)
    if method == "random_flip":
        print("Applying random-flip augmentation — synthetic, see app/ml/augment_data.py.")
        return random_flip_augment(X, y)
    raise ValueError(f"Unknown augmentation method: {method}")


def run_hyperparameter_search(X_train, y_train, base_params: dict) -> dict:
    """
    Randomized search over a reasonable XGBoost hyperparameter space.
    Only worth running with --hyperparam-search, since it multiplies
    training time by n_iter * cv folds. With a small dataset this
    finishes in seconds; with DDXPlus's full ~1M rows, budget real time
    (consider --ddxplus-max-rows for a subsample first).
    """
    param_dist = {
        "n_estimators": [100, 200, 300, 500],
        "max_depth": [3, 4, 5, 6, 8],
        "learning_rate": [0.03, 0.05, 0.08, 0.12, 0.2],
        "subsample": [0.7, 0.8, 0.85, 0.9, 1.0],
        "colsample_bytree": [0.7, 0.8, 0.85, 0.9, 1.0],
        "min_child_weight": [1, 3, 5],
    }
    search = RandomizedSearchCV(
        XGBClassifier(**{k: v for k, v in base_params.items() if k not in param_dist}),
        param_distributions=param_dist,
        n_iter=25,
        cv=3,
        scoring="accuracy",
        random_state=42,
        n_jobs=-1,
        verbose=1,
    )
    search.fit(X_train, y_train)
    print(f"Best CV accuracy from search: {search.best_score_:.4f}")
    print(f"Best params: {search.best_params_}")
    return {**base_params, **search.best_params_}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-source", choices=["bootstrap", "ddxplus", "custom"], default="bootstrap",
        help="Which dataset to train on. See TRAINING_WITH_LARGER_DATASETS.md.",
    )
    parser.add_argument("--custom-csv-dir", default=None, help="Required if --data-source custom.")
    parser.add_argument(
        "--ddxplus-max-rows", type=int, default=None,
        help="Cap rows loaded from DDXPlus (full split is ~1M rows). Omit for the full split.",
    )
    parser.add_argument(
        "--augment", choices=["none", "smote", "random_flip"], default="none",
        help="Synthetic augmentation — see app/ml/augment_data.py before using. Applied to the "
             "training split only, never to the held-out test split.",
    )
    parser.add_argument(
        "--class-weight", action="store_true",
        help="Weight samples inversely to class frequency (sklearn 'balanced' scheme). "
             "Recommended for real-world datasets like DDXPlus, which are NOT artificially "
             "balanced the way the bootstrap dataset is.",
    )
    parser.add_argument(
        "--hyperparam-search", action="store_true",
        help="Run RandomizedSearchCV before final training. Slower; worth it on a larger dataset.",
    )
    args = parser.parse_args()

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    X, y, symptom_cols = get_dataset(args)
    print(f"Loaded {len(X)} labeled records ({args.data_source}), {len(symptom_cols)} symptoms, "
          f"{y.nunique()} distinct conditions.")

    label_encoder = LabelEncoder()
    y_enc = label_encoder.fit_transform(y)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y_enc, test_size=0.2, random_state=42, stratify=y_enc
    )

    if args.augment != "none":
        # Decode back to string labels for the augmentation utilities'
        # interface, then re-encode — keeps augment_data.py decoupled
        # from this script's LabelEncoder.
        y_train_labels = label_encoder.inverse_transform(y_train)
        X_train, y_train_labels_aug = apply_augmentation(
            X_train, pd.Series(y_train_labels), args.augment
        )
        y_train = label_encoder.transform(y_train_labels_aug)
        print(f"Training split after augmentation: {len(X_train)} rows.")

    base_params = dict(
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

    if args.hyperparam_search:
        base_params = run_hyperparameter_search(X_train, y_train, base_params)

    model = XGBClassifier(**base_params)

    sample_weight = compute_sample_weight("balanced", y_train) if args.class_weight else None

    # 5-fold stratified cross-validation on the training split for an
    # honest generalization estimate, in addition to the held-out test set.
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = []
    for fold, (tr_idx, val_idx) in enumerate(skf.split(X_train, y_train), start=1):
        fold_model = XGBClassifier(**model.get_params())
        fold_weight = sample_weight[tr_idx] if sample_weight is not None else None
        fold_model.fit(X_train.iloc[tr_idx], y_train[tr_idx], sample_weight=fold_weight)
        preds = fold_model.predict(X_train.iloc[val_idx])
        acc = accuracy_score(y_train[val_idx], preds)
        cv_scores.append(acc)
        print(f"  fold {fold}: accuracy={acc:.4f}")
    print(f"CV accuracy: mean={np.mean(cv_scores):.4f} std={np.std(cv_scores):.4f}")

    model.fit(X_train, y_train, sample_weight=sample_weight)

    test_pred = model.predict(X_test)
    test_proba = model.predict_proba(X_test)

    metrics = {
        "data_source": args.data_source,
        "augmentation": args.augment,
        "class_weighted": args.class_weight,
        "hyperparameter_search": args.hyperparam_search,
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
    # standard practice once cross-validated performance has been
    # recorded, since every held-out row is otherwise thrown away in a
    # dataset this small. NOTE: for a large dataset (e.g. full DDXPlus),
    # you may prefer to skip this and ship the model fit on X_train only,
    # keeping the test set as a genuinely untouched holdout for later
    # comparison — the tradeoff is a small amount of final-model quality
    # vs. a reusable holdout. Left as the small-dataset-appropriate
    # default; reconsider for a >100k row dataset.
    final_sample_weight = compute_sample_weight("balanced", y_enc) if args.class_weight else None
    final_model = XGBClassifier(**model.get_params())
    final_model.fit(X, y_enc, sample_weight=final_sample_weight)

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
    if args.data_source != "bootstrap":
        print(
            "\nIMPORTANT: you trained on a different dataset than the bootstrap one. "
            "Re-run `python -m app.ml.build_symptom_stats` next (it must be pointed at "
            "the same data source — see that script) to regenerate the symptom-prevalence "
            "table the Dynamic Follow-Up Engine depends on, or question selection will be "
            "silently wrong. Also see TRAINING_WITH_LARGER_DATASETS.md for what else needs "
            "updating (condition->urgency and condition->hospital-capability mappings)."
        )


if __name__ == "__main__":
    main()
