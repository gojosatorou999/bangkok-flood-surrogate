"""Linear probe on cached CLIP embeddings + honest classifier report.
See docs/VARUN_IMPLEMENTATION.md §6 T52.

Trains a logistic-regression probe over `cctv/labelling/labels.csv` (HU5)
joined to the T50 embedding cache, evaluated against zero-shot (v0) on
cameras held out of training entirely (GroupShuffleSplit grouped by
cam_id) -- never report held-out accuracy on a camera the model trained
on. Ships whichever of v0/v1 scores higher on that held-out set by
writing `cctv/classifier/models/CHOSEN.txt`; `write_obs.py` (T53) already
reads that file to pick `model_version`, so leaving it unwritten keeps
H6 on `clip-zs-v0` automatically.

UNUSABLE is never a model class here -- it's assigned rule-based from
quality_flag elsewhere (T53) -- so the probe only ever predicts among
NORMAL / WATERLOGGING / FLOODING / SEVERE_FLOODING. OCCLUDED labels are
ground-truth-only (a labeller couldn't tell), excluded from training.

If there aren't enough labels yet (HU5 pending or still in progress),
`run()` skips training and the report states the exact shortfall instead
of fabricating numbers (rule 8) -- see "Done when" in the task card.
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, cohen_kappa_score, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit

LABELS_CSV = Path("cctv/labelling/labels.csv")
EMBEDDINGS_CACHE = Path("cctv/classifier/cache/embeddings_ViT-B-32.parquet")
ZEROSHOT_CACHE = Path("cctv/classifier/cache/zeroshot_v0.parquet")
MODEL_PATH = Path("cctv/classifier/models/probe_v1.joblib")
CHOSEN_PATH = Path("cctv/classifier/models/CHOSEN.txt")
REPORT_PATH = Path("reports/cctv_classifier_v1.md")

TRAIN_CLASSES = ["NORMAL", "WATERLOGGING", "FLOODING", "SEVERE_FLOODING"]
THREE_CLASS_MAP = {"NORMAL": "NORMAL", "WATERLOGGING": "WATERLOGGING", "FLOODING": "FLOODING", "SEVERE_FLOODING": "FLOODING"}
THREE_CLASSES = ["NORMAL", "WATERLOGGING", "FLOODING"]
C_CANDIDATES = (0.1, 1.0, 10.0)

# [ASSUMPTION] round-number floors, not derived from any target in the parent
# docs (missing from this repo -- see docs/data_gaps.md): need at least one
# held-out camera *and* room for grouped CV folds on the remaining training
# cameras, so fewer than this can't produce an honest held-out-camera score.
MIN_TOTAL_LABELS = 20
MIN_DISTINCT_CAMERAS = 3


def load_primary_and_secondary(labels_csv: Path = LABELS_CSV) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Splits labels.csv into (primary, secondary-double-label) sets.
    `labeller == "b"` is the T51 double-labelling convention; everyone
    else's rows are the training ground truth. Each is deduped to one row
    per sha1 (last write wins), matching labels.csv's own append rule."""
    columns = ["cam_id", "ts_utc", "sha1", "label", "labeller", "labelled_utc"]
    if not labels_csv.exists():
        empty = pd.DataFrame(columns=columns)
        return empty, empty.copy()
    df = pd.read_csv(labels_csv)
    primary = df[df["labeller"] != "b"].drop_duplicates(subset="sha1", keep="last")
    secondary = df[df["labeller"] == "b"].drop_duplicates(subset="sha1", keep="last")
    return primary, secondary


def inter_rater_kappa(primary: pd.DataFrame, secondary: pd.DataFrame) -> float | None:
    """Cohen's kappa on the sha1s both labellers scored. None when there's
    no double-labelled overlap yet."""
    if primary.empty or secondary.empty:
        return None
    joined = primary.merge(secondary, on="sha1", suffixes=("_a", "_b"))
    if joined.empty:
        return None
    return float(cohen_kappa_score(joined["label_a"], joined["label_b"]))


def load_training_frame(primary: pd.DataFrame, embeddings_cache: Path = EMBEDDINGS_CACHE) -> pd.DataFrame:
    """Primary labels (OCCLUDED/UNUSABLE excluded) joined to their cached
    embedding, one row per sha1."""
    trainable = primary[primary["label"].isin(TRAIN_CLASSES)]
    if trainable.empty or not embeddings_cache.exists():
        return pd.DataFrame(columns=["cam_id", "sha1", "label", "emb"])
    emb_df = pd.read_parquet(embeddings_cache).drop_duplicates(subset="sha1", keep="last")
    joined = trainable.merge(emb_df[["sha1", "emb"]], on="sha1", how="inner")
    return joined[["cam_id", "sha1", "label", "emb"]].reset_index(drop=True)


def grouped_split(frame: pd.DataFrame, test_size: float = 0.3, random_state: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Camera-held-out split: no camera appears in both train and test."""
    splitter = GroupShuffleSplit(test_size=test_size, random_state=random_state, n_splits=1)
    train_idx, test_idx = next(splitter.split(frame, groups=frame["cam_id"]))
    train, test = frame.iloc[train_idx], frame.iloc[test_idx]
    assert set(train["cam_id"]).isdisjoint(set(test["cam_id"])), "train/test camera sets must be disjoint"
    return train, test


def select_c(train: pd.DataFrame, candidates: tuple[float, ...] = C_CANDIDATES) -> float:
    """Grouped CV on the train split only -- never touches the held-out
    test cameras. Falls back to the middle candidate if there aren't
    enough distinct training cameras to run CV at all."""
    X = np.stack(train["emb"].to_numpy())
    y = train["label"].to_numpy()
    groups = train["cam_id"].to_numpy()
    n_splits = min(3, train["cam_id"].nunique())
    if n_splits < 2:
        return candidates[len(candidates) // 2]

    best_c, best_score = candidates[0], -1.0
    for c in candidates:
        scores = []
        for tr_idx, va_idx in GroupKFold(n_splits=n_splits).split(X, y, groups=groups):
            clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=c).fit(X[tr_idx], y[tr_idx])
            scores.append(f1_score(y[va_idx], clf.predict(X[va_idx]), average="macro", zero_division=0))
        mean_score = float(np.mean(scores))
        if mean_score > best_score:
            best_c, best_score = c, mean_score
    return best_c


def train_probe(train: pd.DataFrame, c: float) -> LogisticRegression:
    X = np.stack(train["emb"].to_numpy())
    y = train["label"].to_numpy()
    return LogisticRegression(max_iter=2000, class_weight="balanced", C=c).fit(X, y)


def _evaluate(y_true, y_pred, labels: list[str]) -> dict:
    return {
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", labels=labels, zero_division=0)),
        "report": classification_report(y_true, y_pred, labels=labels, output_dict=True, zero_division=0),
        "confusion": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        "labels": labels,
    }


def zero_shot_predictions(test: pd.DataFrame, zeroshot_cache: Path = ZEROSHOT_CACHE) -> np.ndarray:
    """v0 baseline: the cached zero-shot argmax for each held-out sha1."""
    if not zeroshot_cache.exists():
        return np.full(len(test), None)
    zs = pd.read_parquet(zeroshot_cache)[["sha1", "argmax_class"]].drop_duplicates(subset="sha1", keep="last")
    merged = test.merge(zs, on="sha1", how="left")
    return merged["argmax_class"].to_numpy()


def _three_class_variant(frame: pd.DataFrame, zeroshot_cache: Path, random_state: int = 42) -> dict | None:
    """NORMAL / WATERLOGGING / FLOODING+SEVERE, for when a 4-class split
    would leave some class too thin to evaluate honestly (card §6 T52)."""
    frame3 = frame.assign(label=frame["label"].map(THREE_CLASS_MAP))
    if frame3["cam_id"].nunique() < MIN_DISTINCT_CAMERAS:
        return None
    train, test = grouped_split(frame3, random_state=random_state)
    c = select_c(train)
    clf = train_probe(train, c)
    X_test = np.stack(test["emb"].to_numpy())
    v1_eval = _evaluate(test["label"].to_numpy(), clf.predict(X_test), THREE_CLASSES)
    v0_pred = zero_shot_predictions(test, zeroshot_cache)
    v0_pred = np.array([THREE_CLASS_MAP.get(p, p) for p in v0_pred])
    v0_eval = _evaluate(test["label"].to_numpy(), v0_pred, THREE_CLASSES)
    return {"chosen_c": c, "v0": v0_eval, "v1": v1_eval}


def write_report(result: dict, report_path: Path = REPORT_PATH) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# CCTV flood-severity classifier -- v1 report", "", "*Visual flood severity proxy, never \"depth\".*", ""]

    lines += ["## Data", ""]
    lines.append(f"- Labelled frames (usable, {'/'.join(TRAIN_CLASSES)}): **{result['n_total']}**")
    lines.append(f"- Distinct cameras labelled: **{result['n_cameras']}**")
    if result["class_counts"]:
        lines.append("- Per-class counts: " + ", ".join(f"{k}={v}" for k, v in sorted(result["class_counts"].items())))
    kappa_str = f"{result['kappa']:.3f}" if result["kappa"] is not None else "N/A (no double-labelled overlap yet)"
    lines.append(f"- Inter-rater kappa (double-labelled subset, ceiling for v1): {kappa_str}")
    lines.append("")

    if result["status"] == "insufficient_labels":
        lines += [
            "## Result",
            "",
            f"**insufficient labels: {result['n_total']}** across {result['n_cameras']} camera(s) "
            f"(need >= {MIN_TOTAL_LABELS} labels across >= {MIN_DISTINCT_CAMERAS} cameras for an honest "
            "camera-held-out split). No probe was trained; shipping stays on zero-shot `clip-zs-v0` "
            "(`cctv/classifier/models/CHOSEN.txt` left unwritten).",
            "",
            "## Limitations",
            "",
            "- HU5 (frame labelling, 200-400 frames + a 50-frame double-label for kappa) has not "
            "produced enough labels yet to train or evaluate a probe. Re-run `python -m cctv.classifier.probe` "
            "once more labels exist.",
            "- CCTV output is always a *visual flood severity proxy*, never a depth measurement.",
            "- \"Feasibility prototype -- not for flood warning.\"",
            "",
        ]
        report_path.write_text("\n".join(lines))
        return

    lines += ["## Method", "", "- Embeddings: cached CLIP ViT-B-32 (laion2b_s34b_b79k), T50.",
              "- Split: `GroupShuffleSplit(test_size=0.3, random_state=42)` grouped by `cam_id` -- held-out "
              "cameras never appear in training.",
              f"- Model: `LogisticRegression(class_weight=\"balanced\")`, C={result['chosen_c']} "
              f"(chosen by grouped CV over {C_CANDIDATES} on the train cameras only).",
              "- UNUSABLE is rule-based (quality_flag), not predicted by either model here.", ""]

    def _results_table(v0: dict, v1: dict, labels: list[str]) -> list[str]:
        out = ["| Class | v0 P | v0 R | v0 F1 | v1 P | v1 R | v1 F1 | Support |", "|---|---|---|---|---|---|---|---|"]
        for cls in labels:
            r0, r1 = v0["report"].get(cls, {}), v1["report"].get(cls, {})
            out.append(
                f"| {cls} | {r0.get('precision', 0):.2f} | {r0.get('recall', 0):.2f} | {r0.get('f1-score', 0):.2f} | "
                f"{r1.get('precision', 0):.2f} | {r1.get('recall', 0):.2f} | {r1.get('f1-score', 0):.2f} | {int(r1.get('support', 0))} |"
            )
        out.append(f"| **macro-F1** | | | **{v0['macro_f1']:.3f}** | | | **{v1['macro_f1']:.3f}** | |")
        return out

    lines += ["## Results (held-out cameras)", ""]
    lines += _results_table(result["v0"], result["v1"], result["v0"]["labels"])
    lines.append("")
    lines.append(f"Confusion matrix (v1, rows=true/cols=pred, order={result['v0']['labels']}): `{result['v1']['confusion']}`")
    lines.append("")
    lines.append(f"**Shipped model: {result['shipped']}** (higher held-out macro-F1).")
    lines.append("")

    if result.get("three_class"):
        tc = result["three_class"]
        lines += ["## 3-class variant (NORMAL / WATERLOGGING / FLOODING+SEVERE)", "",
                  "At least one class had fewer than 10 labels, so the 4-class split above may be unreliable "
                  "for that class; this collapses FLOODING+SEVERE_FLOODING for a steadier read.", ""]
        lines += _results_table(tc["v0"], tc["v1"], THREE_CLASSES)
        lines.append("")

    lines += ["## Limitations", "",
              "- Class imbalance and daytime bias are expected until more labels cover more conditions.",
              "- CCTV output is always a *visual flood severity proxy*, never a depth measurement.",
              "- \"Feasibility prototype -- not for flood warning.\"", ""]
    report_path.write_text("\n".join(lines))


def run(
    labels_csv: Path = LABELS_CSV,
    embeddings_cache: Path = EMBEDDINGS_CACHE,
    zeroshot_cache: Path = ZEROSHOT_CACHE,
    model_path: Path = MODEL_PATH,
    chosen_path: Path = CHOSEN_PATH,
    report_path: Path = REPORT_PATH,
) -> dict:
    primary, secondary = load_primary_and_secondary(labels_csv)
    kappa = inter_rater_kappa(primary, secondary)
    frame = load_training_frame(primary, embeddings_cache)
    class_counts = frame["label"].value_counts().to_dict()
    n_total, n_cams = len(frame), frame["cam_id"].nunique()

    if n_total < MIN_TOTAL_LABELS or n_cams < MIN_DISTINCT_CAMERAS:
        result = {
            "status": "insufficient_labels",
            "n_total": n_total,
            "n_cameras": n_cams,
            "class_counts": class_counts,
            "kappa": kappa,
        }
        write_report(result, report_path)
        return result

    train, test = grouped_split(frame)
    c = select_c(train)
    clf = train_probe(train, c)

    X_test = np.stack(test["emb"].to_numpy())
    y_test = test["label"].to_numpy()
    v1_eval = _evaluate(y_test, clf.predict(X_test), TRAIN_CLASSES)
    v0_eval = _evaluate(y_test, zero_shot_predictions(test, zeroshot_cache), TRAIN_CLASSES)

    three_class = _three_class_variant(frame, zeroshot_cache) if any(v < 10 for v in class_counts.values()) else None

    shipped = "v1" if v1_eval["macro_f1"] >= v0_eval["macro_f1"] else "v0"
    if shipped == "v1":
        model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(clf, model_path)
        chosen_path.write_text("probe_v1\n")

    result = {
        "status": "trained",
        "n_total": n_total,
        "n_cameras": n_cams,
        "class_counts": class_counts,
        "kappa": kappa,
        "chosen_c": c,
        "v0": v0_eval,
        "v1": v1_eval,
        "three_class": three_class,
        "shipped": shipped,
    }
    write_report(result, report_path)
    return result


def main() -> None:
    result = run()
    if result["status"] == "insufficient_labels":
        print(f"insufficient labels: {result['n_total']} across {result['n_cameras']} camera(s); report written")
    else:
        print(f"trained; v0 macro-F1={result['v0']['macro_f1']:.3f} v1 macro-F1={result['v1']['macro_f1']:.3f} "
              f"shipped={result['shipped']}; report written")


if __name__ == "__main__":
    main()
