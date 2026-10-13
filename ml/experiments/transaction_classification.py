"""Experiment 03: human-only targets, frozen protocols, local representation comparison."""

import argparse
import csv
import json
import os
import platform
import time
from collections import Counter
from datetime import date
from importlib.metadata import version
from pathlib import Path

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler
from threadpoolctl import threadpool_limits

from data_pipeline.labels.contracts import CATEGORIES, CONTEXTS
from data_pipeline.labels.review_input import parse_import
from ml.evaluation.classification import (
    ABSTAIN,
    THRESHOLDS,
    abstain,
    error_patterns,
    hybrid,
    metrics,
    seen_analysis,
    selective,
)
from ml.features.transaction_embeddings import embeddings
from ml.features.transactions import (
    SEED,
    STRUCTURED_FIELDS,
    TEXT_FIELDS,
    cohort,
    feature_rows,
    fingerprint,
    merchant,
    rule_predictions,
    split_indices,
    structured,
    texts,
)

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / "ml/evaluation/output/experiment_03"
MODELS = ("tfidf_text", "tfidf_structured", "e5_text")
LR_CONFIG = {
    "C": 1.0,
    "max_iter": 2000,
    "solver": "lbfgs",
    "class_weight": None,
    "random_state": SEED,
    "tol": 1e-4,
}


def tfidf_pipeline(with_structured=False):
    text = Pipeline(
        [
            ("text", FunctionTransformer(texts)),
            (
                "tfidf",
                TfidfVectorizer(
                    ngram_range=(1, 2), min_df=1, sublinear_tf=True, strip_accents=None
                ),
            ),
        ]
    )
    features = text
    if with_structured:
        numbers = Pipeline(
            [
                ("select", FunctionTransformer(structured)),
                ("dict", DictVectorizer()),
                ("scale", StandardScaler(with_mean=False)),
            ]
        )
        features = FeatureUnion([("text", text), ("structured", numbers)])
    return Pipeline([("features", features), ("classifier", LogisticRegression(**LR_CONFIG))])


def load_dataset(path, review_path):
    raw = Path(path).read_bytes()
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    expected = {
        "transaction_id",
        *TEXT_FIELDS,
        *STRUCTURED_FIELDS,
        "confirmed_category",
        "confirmed_business_context",
    }
    if not rows or set(rows[0]) != expected:
        raise ValueError("Ground-truth schema mismatch")
    review_raw = Path(review_path).read_bytes()
    reviewed, _ = parse_import(review_raw)
    approved = {r["transaction_id"]: r for r in reviewed if r["review_status"] == "REVIEWED"}
    if len({r["transaction_id"] for r in rows}) != len(rows) or set(approved) != {
        r["transaction_id"] for r in rows
    }:
        raise ValueError("Ground truth must exactly match finalized reviewed subset")
    for row in rows:
        source = approved[row["transaction_id"]]
        if row["confirmed_category"] != source["reviewed_category"] or (
            row["confirmed_business_context"] != source["reviewed_business_context"]
        ):
            raise ValueError("Human labels changed")
        booking = date.fromisoformat(source["booking_date"])
        if int(row["month"]) != booking.month or int(row["day_of_week"]) != booking.weekday():
            raise ValueError("Calendar features changed")
        if any(row[k] != source[k] for k in TEXT_FIELDS + ("amount", "direction")):
            raise ValueError("Source features changed")
    import hashlib

    return sorted(rows, key=lambda r: r["transaction_id"]), {
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "reviewed_label_source_sha256": hashlib.sha256(review_raw).hexdigest(),
    }


def write_csv(path, rows):
    if rows:
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def make_plots(summary, output):
    os.environ.setdefault("MPLCONFIGDIR", str(PRIVATE / "matplotlib-cache"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, target in zip(axes, ("context", "category"), strict=True):
        x = np.arange(len(MODELS))
        for offset, view in [(-0.25, "ordinary"), (0.0, "grouped"), (0.25, "grouped_cv")]:
            ax.bar(
                x + offset,
                [
                    (
                        summary["targets"][target]["grouped_cv"]
                        if view == "grouped_cv"
                        else summary["targets"][target]["views"][view]
                    )["models"][m]["metrics"]["macro_f1"]
                    for m in MODELS
                ],
                width=0.25,
                label=view,
            )
        ax.set_xticks(x, MODELS, rotation=15)
        ax.set_ylim(0, 1)
        ax.set_title(f"{target}: fixed-task macro F1")
        ax.legend()
    fig.tight_layout()
    fig.savefig(output / "macro_f1.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(2, 3, figsize=(13, 8))
    for i, view in enumerate(("ordinary", "grouped")):
        for j, model in enumerate(MODELS):
            result = summary["targets"]["context"]["views"][view]["models"][model]["metrics"]
            ax = axes[i, j]
            ax.imshow(result["confusion_matrix"], cmap="Blues")
            ax.set_xticks(range(3), result["confusion_labels"], rotation=45)
            ax.set_yticks(range(3), result["confusion_labels"])
            for a, row in enumerate(result["confusion_matrix"]):
                for b, val in enumerate(row):
                    ax.text(b, a, str(val), ha="center", va="center")
            ax.set_title(f"{view} / {model}")
            ax.set_xlabel("Predicted")
            ax.set_ylabel("True")
    fig.tight_layout()
    fig.savefig(output / "context_confusions.png", dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 4))
    for view in ("ordinary", "grouped"):
        for model in MODELS:
            result = summary["targets"]["context"]["views"][view]["models"][model]["abstention"]
            ax.plot(
                THRESHOLDS,
                [result[str(t)]["coverage"] for t in THRESHOLDS],
                marker="o",
                label=f"{view}/{model}",
            )
    ax.set(xlabel="Fixed confidence threshold", ylabel="Prediction coverage", ylim=(0, 1))
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(output / "coverage.png", dpi=150)
    plt.close(fig)


def evaluate(rows, vectors):
    results, predictions, qualitative, split_records = {}, [], [], {}
    for target in ("context", "category"):
        field = "confirmed_business_context" if target == "context" else "confirmed_category"
        keep, excluded = cohort(rows, target)
        selected = [rows[i] for i in keep]
        y = np.array([r[field] for r in selected])
        labels = sorted(set(y))
        groups = np.array([merchant(r) for r in selected])
        rules = rule_predictions(selected, target)
        task = {
            "all_reviewed_counts": dict(Counter(r[field] for r in rows)),
            "scored_rows": len(keep),
            "scored_classes": labels,
            "excluded_counts": dict(Counter(rows[i][field] for i in excluded)),
            "absent_classes": sorted(
                set(CONTEXTS if target == "context" else CATEGORIES) - set(r[field] for r in rows)
            ),
            "merchant_groups_per_class": {label: len(set(groups[y == label])) for label in labels},
            "rules_full_scored_cohort": selective(y, rules, labels),
            "rules_all_reviewed": selective(
                [r[field] for r in rows],
                rule_predictions(rows, target),
                sorted({r[field] for r in rows}),
            ),
            "views": {},
        }
        plans = [(view, *split_indices(y, groups, view)) for view in ("ordinary", "grouped")]
        plans.extend(
            (f"grouped_fold_{fold}", np.sort(train), np.sort(test))
            for fold, (train, test) in enumerate(
                GroupKFold(n_splits=3).split(np.arange(len(y)), y, groups), 1
            )
        )
        for view, train, test in plans:
            ids = {
                "train": [selected[i]["transaction_id"] for i in train],
                "test": [selected[i]["transaction_id"] for i in test],
            }
            split_records[f"{target}_{view}"] = ids
            split = {
                "train_rows": len(train),
                "test_rows": len(test),
                "train_counts": dict(sorted(Counter(y[train]).items())),
                "test_counts": dict(sorted(Counter(y[test]).items())),
                "train_merchant_groups": len(set(groups[train])),
                "test_merchant_groups": len(set(groups[test])),
                "merchant_overlap": len(set(groups[train]) & set(groups[test])),
                "classes_missing_train": sorted(set(labels) - set(y[train])),
                "classes_missing_test": sorted(set(labels) - set(y[test])),
                "split_sha256": fingerprint(ids),
                "rules": selective(y[test], rules[test], labels),
                "models": {},
            }
            if view.startswith("grouped"):
                assert split["merchant_overlap"] == 0
            for name in MODELS:
                started = time.perf_counter()
                if name == "e5_text":
                    model = LogisticRegression(**LR_CONFIG)
                    x_train, x_test, x_excluded = (
                        vectors[keep[train]],
                        vectors[keep[test]],
                        vectors[excluded],
                    )
                else:
                    model = tfidf_pipeline(name == "tfidf_structured")
                    x_train = feature_rows([selected[i] for i in train])
                    x_test = feature_rows([selected[i] for i in test])
                    x_excluded = feature_rows([rows[i] for i in excluded])
                model.fit(x_train, y[train])
                probs = model.predict_proba(x_test)
                pred = model.classes_[np.argmax(probs, axis=1)]
                confidence = probs.max(axis=1)
                run = {
                    "metrics": metrics(y[test], pred, labels),
                    "merchant_analysis": seen_analysis(
                        y[test], pred, groups[train], groups[test], labels
                    ),
                    "error_patterns": error_patterns(y[test], pred),
                    "abstention": {
                        str(t): selective(y[test], abstain(pred, confidence, t), labels)
                        for t in THRESHOLDS
                    },
                    "hybrid_threshold": 0.7,
                    "hybrid": selective(y[test], hybrid(rules[test], pred, confidence), labels),
                }
                run["hybrid"]["rule_coverage"] = float(np.mean(rules[test] != ABSTAIN))
                run["hybrid"]["ml_fallback_coverage"] = float(
                    np.mean((rules[test] == ABSTAIN) & (confidence >= 0.7))
                )
                split["models"][name] = run
                for k, i in enumerate(test):
                    predictions.append(
                        {
                            "target": target,
                            "view": view,
                            "model": name,
                            "transaction_id": selected[i]["transaction_id"],
                            "text": texts([selected[i]])[0],
                            "merchant_group": groups[i],
                            "seen_merchant": bool(groups[i] in set(groups[train])),
                            "true": y[i],
                            "predicted": pred[k],
                            "confidence": float(confidence[k]),
                            "rule_prediction": rules[i],
                            "runtime_seconds": time.perf_counter() - started,
                        }
                    )
                if len(excluded):
                    excluded_probs = model.predict_proba(x_excluded)
                    for k, i in enumerate(excluded):
                        confidence_ = float(excluded_probs[k].max())
                        qualitative.append(
                            {
                                "target": target,
                                "view": view,
                                "model": name,
                                "transaction_id": rows[i]["transaction_id"],
                                "true": rows[i][field],
                                "predicted": model.classes_[excluded_probs[k].argmax()],
                                "confidence": confidence_,
                                "abstains_at_0.7": confidence_ < 0.7,
                            }
                        )
            task["views"][view] = split
        pooled = {
            "folds": 3,
            "test_rows": len(selected),
            "merchant_overlap": 0,
            "models": {},
            "rules": selective(y, rules, labels),
        }
        for name in MODELS:
            records = [
                r
                for r in predictions
                if r["target"] == target
                and r["model"] == name
                and r["view"].startswith("grouped_fold_")
            ]
            assert len(records) == len(selected)
            assert len({r["transaction_id"] for r in records}) == len(selected)
            truth = np.array([r["true"] for r in records])
            pred = np.array([r["predicted"] for r in records])
            confidence = np.array([r["confidence"] for r in records])
            rule = np.array([r["rule_prediction"] for r in records])
            fold_scores = [
                task["views"][f"grouped_fold_{f}"]["models"][name]["metrics"]["macro_f1"]
                for f in range(1, 4)
            ]
            pooled["models"][name] = {
                "metrics": metrics(truth, pred, labels),
                "fold_macro_f1_mean": float(np.mean(fold_scores)),
                "fold_macro_f1_std": float(np.std(fold_scores)),
                "merchant_analysis": seen_analysis(
                    truth, pred, [], [r["merchant_group"] for r in records], labels
                ),
                "error_patterns": error_patterns(truth, pred),
                "abstention": {
                    str(t): selective(truth, abstain(pred, confidence, t), labels)
                    for t in THRESHOLDS
                },
                "hybrid_threshold": 0.7,
                "hybrid": {
                    **selective(truth, hybrid(rule, pred, confidence), labels),
                    "rule_coverage": float(np.mean(rule != ABSTAIN)),
                    "ml_fallback_coverage": float(np.mean((rule == ABSTAIN) & (confidence >= 0.7))),
                },
            }
        task["grouped_cv"] = pooled
        results[target] = task
    return results, predictions, qualitative, split_records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", default="run1")
    parser.add_argument("--refresh-embeddings", action="store_true")
    args = parser.parse_args()
    if Path(args.run_name).name != args.run_name:
        raise ValueError("Run name must be a basename")
    output = PRIVATE / args.run_name
    output.mkdir(parents=True, exist_ok=False)
    rows, hashes = load_dataset(
        ROOT / "data/processed/bank/ground_truth.csv",
        ROOT / "data/processed/bank/review_queue_v2_grouped.csv",
    )
    vectors, embedding_info = embeddings(
        texts(feature_rows(rows)), PRIVATE / "embedding_cache", refresh=args.refresh_embeddings
    )
    with threadpool_limits(limits=1):
        targets, predictions, qualitative, splits = evaluate(rows, vectors)
    summary = {
        "experiment": "03",
        "seed": SEED,
        "dataset_rows": len(rows),
        **hashes,
        "versions": {
            "python": platform.python_version(),
            **{
                p: version(p)
                for p in [
                    "scikit-learn",
                    "sentence-transformers",
                    "transformers",
                    "torch",
                    "polars",
                    "numpy",
                ]
            },
        },
        "feature_config": {
            "text_fields": TEXT_FIELDS,
            "structured_fields": STRUCTURED_FIELDS,
            "amount_transform": "signed_log1p",
            "text_ngram_range": [1, 2],
            "class_weight": None,
            "lr": LR_CONFIG,
        },
        "embedding": {
            k: v
            for k, v in embedding_info.items()
            if k not in ("runtime_seconds", "cache_hit", "previous_cache_max_absolute_delta")
        },
        "targets": targets,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    (output / "runtime.json").write_text(json.dumps(embedding_info, indent=2))
    (output / "splits.json").write_text(json.dumps(splits, indent=2))
    write_csv(output / "predictions.csv", predictions)
    write_csv(output / "errors.csv", [r for r in predictions if r["true"] != r["predicted"]])
    write_csv(output / "qualitative_excluded.csv", qualitative)
    make_plots(summary, output)
    print(
        json.dumps(
            {
                "run": args.run_name,
                "summary": str(output / "summary.json"),
                "embedding": embedding_info,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
