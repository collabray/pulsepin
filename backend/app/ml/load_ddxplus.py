"""
Adapter to plug the DDXPlus dataset into the existing training pipeline
(train_triage_model.py) as a drop-in replacement for the small bootstrap
dataset in app/ml/data/.

DDXPlus (Tchango et al., NeurIPS 2022 Datasets & Benchmarks track) is a
large-scale (1.3M patients), clinically-modeled synthetic dataset covering
49 pathologies with rich per-patient symptom/antecedent evidence, released
under CC-BY 4.0. It is NOT the small textbook dataset currently shipped in
this repo — see LIMITATIONS.md for why the two shouldn't be confused.

Why this file is a stub and not a working downloader: the dataset's actual
CSV/JSON release files are hosted on figshare
(https://figshare.com/articles/dataset/DDXPlus_Dataset/22687585), which
was not a reachable domain from the sandboxed environment this project was
built in. Rather than silently skip better data or fabricate a fake
download, this file documents exactly what to implement once you (running
with normal internet access) have downloaded the real files.

To finish this adapter:
  1. Download release_train_patients.csv, release_validate_patients.csv,
     release_test_patients.csv, and release_evidences.json /
     release_conditions.json from the figshare release above.
  2. Place them under app/ml/data/ddxplus/.
  3. Implement `load_ddxplus_dataset()` below: DDXPlus rows are richer
     than binary symptom flags (each patient has a differential diagnosis,
     evidence with values/categories, demographics) — you will likely want
     to binarize evidence presence/absence per symptom (matching this
     repo's existing X/y shape) as a first pass, and consider a follow-up
     iteration that uses the richer evidence structure directly instead of
     discarding it.
  4. Point train_triage_model.py's `load_dataset()` at this function
     instead of the bootstrap CSVs (a one-line change — both must return
     the same (X: DataFrame, y: Series, symptom_cols: list[str]) shape).
  5. Re-run `python -m app.ml.audit_dataset` — with real DDXPlus data you
     should see class imbalance that reflects the paper's documented
     prevalence design (not the artificial uniform balance the bootstrap
     dataset has), and a much larger unique-symptom-patterns-per-class
     count.
"""
from pathlib import Path

DDXPLUS_DIR = Path(__file__).parent / "data" / "ddxplus"


def load_ddxplus_dataset():
    if not DDXPLUS_DIR.exists():
        raise FileNotFoundError(
            f"{DDXPLUS_DIR} does not exist. Download the DDXPlus release files "
            "from https://figshare.com/articles/dataset/DDXPlus_Dataset/22687585 "
            "and place them there before calling this function. See the module "
            "docstring in app/ml/load_ddxplus.py for the full file list and the "
            "remaining implementation steps."
        )
    raise NotImplementedError(
        "DDXPlus files were found, but the CSV/JSON parsing + binarization step "
        "described in this module's docstring (step 3) has not been implemented "
        "yet. This is intentionally left for whoever has access to the real "
        "files to finish, rather than guessed at blind."
    )
