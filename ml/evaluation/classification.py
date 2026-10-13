"""Support-aware metrics, fixed abstention thresholds and evaluation-only hybrid."""

from collections import Counter

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support

THRESHOLDS = (0.5, 0.6, 0.7, 0.8)
ABSTAIN = "NEEDS_REVIEW"


def metrics(y, predicted, labels):
    y, predicted = np.asarray(y), np.asarray(predicted)
    if len(y) == 0:
        return {
            "rows": 0,
            "accuracy": None,
            "macro_f1": None,
            "weighted_f1": None,
            "per_class": {},
            "confusion_labels": list(labels),
            "confusion_matrix": [],
        }
    precision, recall, f1, support = precision_recall_fscore_support(
        y, predicted, labels=labels, zero_division=0
    )
    # Fixed task labels, including zero-support classes, make fold/ablation comparisons explicit.
    result = {
        "rows": len(y),
        "accuracy": float(accuracy_score(y, predicted)),
        "macro_f1": float(np.mean(f1)),
        "weighted_f1": float(np.sum(f1 * support) / len(y)),
        "per_class": {
            label: {"precision": float(p), "recall": float(r), "f1": float(f), "support": int(n)}
            for label, p, r, f, n in zip(labels, precision, recall, f1, support, strict=True)
        },
    }
    # Rules may predict a category excluded from the supervised cohort. Keep
    # those errors visible without changing the fixed-task macro-F1 labels.
    extra_labels = sorted((set(y) | set(predicted)) - set(labels) - {ABSTAIN})
    matrix_labels = list(labels) + extra_labels + ([ABSTAIN] if ABSTAIN in predicted else [])
    result.update(
        confusion_labels=matrix_labels,
        confusion_matrix=confusion_matrix(y, predicted, labels=matrix_labels).tolist(),
    )
    return result


def selective(y, predicted, labels):
    mask = np.asarray(predicted) != ABSTAIN
    retained = metrics(np.asarray(y)[mask], np.asarray(predicted)[mask], labels)
    return {
        "coverage": float(mask.mean()) if len(mask) else 0.0,
        "abstention_rate": float((~mask).mean()) if len(mask) else 1.0,
        "retained": retained,
        "correct_over_all_rows": float(np.mean(np.asarray(y) == predicted)) if len(mask) else None,
    }


def abstain(predictions, probabilities, threshold):
    return np.where(np.asarray(probabilities) >= threshold, predictions, ABSTAIN)


def hybrid(rules, predictions, probabilities, threshold=0.7):
    rules = np.asarray(rules)
    return np.where(rules != ABSTAIN, rules, abstain(predictions, probabilities, threshold))


def seen_analysis(y, predictions, train_groups, test_groups, labels):
    seen = np.array([g in set(train_groups) for g in test_groups])
    return {
        "seen_test_fraction": float(seen.mean()),
        "merchant_overlap_count": len(set(train_groups) & set(test_groups)),
        "seen": metrics(np.asarray(y)[seen], np.asarray(predictions)[seen], labels),
        "unseen": metrics(np.asarray(y)[~seen], np.asarray(predictions)[~seen], labels),
    }


def error_patterns(y, predictions):
    return [
        {"true": a, "predicted": b, "count": count}
        for (a, b), count in sorted(
            Counter(
                (str(a), str(b)) for a, b in zip(y, predictions, strict=True) if a != b
            ).items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
