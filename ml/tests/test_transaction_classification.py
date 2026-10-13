"""Synthetic-only protocol, leakage, split, metrics and cache regression tests."""

import copy

import numpy as np
import pytest

from ml.evaluation.classification import (
    ABSTAIN,
    abstain,
    hybrid,
    metrics,
    seen_analysis,
    selective,
)
from ml.experiments.transaction_classification import LR_CONFIG, MODELS, evaluate, tfidf_pipeline
from ml.features.transaction_embeddings import DIMENSION, cache_identity, validate_embeddings
from ml.features.transactions import (
    STRUCTURED_FIELDS,
    TEXT_FIELDS,
    cohort,
    combined_text,
    feature_rows,
    merchant,
    rule_predictions,
    split_indices,
    structured,
)


def synthetic():
    rows = []
    for j, (context, category) in enumerate(
        [("PERSONAL", "OTHER"), ("PROPERTY", "ELECTRICITY"), ("FORESTRY", "FORESTRY_SERVICE")]
    ):
        for i in range(20):
            rows.append(
                {
                    "transaction_id": f"{j}-{i}",
                    "normalized_counterparty": f"{category.lower()} merchant {i // 2}",
                    "ultimate_recipient": None,
                    "message": category.lower(),
                    "transaction_type_code": "106",
                    "amount": "-12.34",
                    "direction": "OUTGOING",
                    "month": 1,
                    "day_of_week": 2,
                    "confirmed_category": category,
                    "confirmed_business_context": context,
                }
            )
    return rows


def test_combined_text_has_clear_separators_and_nulls():
    text = combined_text({"message": "Hello", "amount": 99, "confirmed_category": "LEAK"})
    assert text == (
        "normalized_counterparty:  | ultimate_recipient:  | "
        "message: Hello | transaction_type_code: "
    )
    assert "None" not in text and "99" not in text and "LEAK" not in text


@pytest.mark.parametrize(
    "field",
    [
        "transaction_id",
        "confirmed_category",
        "confirmed_business_context",
        "suggested_category",
        "suggested_business_context",
        "rule_metadata",
        "review_notes",
        "review_group",
        "evidence_status",
        "review_hint",
    ],
)
def test_forbidden_fields_cannot_affect_features(field):
    row = synthetic()[0]
    before = feature_rows([row])
    row[field] = "LEAK"
    assert feature_rows([row]) == before
    assert set(before[0]) == set(TEXT_FIELDS + STRUCTURED_FIELDS)


def test_unknown_context_and_sparse_category_exclusions():
    rows = synthetic()
    rows.extend(
        [
            {**rows[0], "confirmed_business_context": "UNKNOWN", "confirmed_category": "UNKNOWN"},
            {**rows[0], "confirmed_category": "TRANSFER"},
            *[{**rows[0], "confirmed_category": "TIMBER_INCOME"} for _ in range(2)],
        ]
    )
    keep, excluded = cohort(rows, "context")
    assert len(keep) == 63 and len(excluded) == 1
    keep, excluded = cohort(rows, "category")
    assert len(keep) == 60 and len(excluded) == 4
    assert all(
        rows[i]["confirmed_category"]
        not in {"UNKNOWN", "TRANSFER", "TIMBER_INCOME", "SUBSCRIPTION"}
        for i in keep
    )


def test_effective_merchant_and_aliases():
    assert merchant(
        {"normalized_counterparty": "processor", "ultimate_recipient": "Elenia Verkko Oy"}
    ) == merchant({"normalized_counterparty": "ELENIA VERKKO OYJ."})
    assert (
        merchant({"normalized_counterparty": "fallback", "ultimate_recipient": "123"}) == "fallback"
    )
    assert (
        merchant({"normalized_counterparty": "fallback", "ultimate_recipient": "  Merchant  "})
        == "merchant"
    )


@pytest.mark.parametrize("view", ["ordinary", "grouped"])
def test_split_reproducibility_and_no_overlap(view):
    rows = synthetic()
    y = [r["confirmed_business_context"] for r in rows]
    groups = [merchant(r) for r in rows]
    a, b = split_indices(y, groups, view)
    c, d = split_indices(y, groups, view)
    assert np.array_equal(a, c) and np.array_equal(b, d)
    assert len(a) + len(b) == len(rows) and not set(a) & set(b)
    if view == "grouped":
        assert not {groups[i] for i in a} & {groups[i] for i in b}
    else:
        assert set(np.array(y)[a]) == set(y) == set(np.array(y)[b])


@pytest.mark.parametrize("include_structured", [False, True])
def test_tfidf_pipeline_and_predefined_ablation(include_structured):
    rows = synthetic()
    features = feature_rows(rows)
    y = [r["confirmed_business_context"] for r in rows]
    model = tfidf_pipeline(include_structured).fit(features, y)
    assert model.predict_proba(features).shape == (60, 3)
    assert len(model.predict(features)) == 60
    transformed = model["features"].transform(features)
    assert transformed.shape[0] == 60
    assert (
        ("structured" in dict(model["features"].transformer_list))
        if include_structured
        else hasattr(model["features"], "steps")
    )
    assert LR_CONFIG["class_weight"] is None


def test_structured_amount_sign_and_no_targets():
    row = synthetic()[0]
    values = structured([row])[0]
    assert values["signed_log_amount"] < 0
    assert set(values) == {"signed_log_amount", "direction", "month", "day_of_week"}


def test_embedding_shape_and_normalization():
    array = np.ones((3, DIMENSION), dtype=np.float32) / np.sqrt(DIMENSION)
    validate_embeddings(array, 3)
    with pytest.raises(ValueError):
        validate_embeddings(array, 4)
    with pytest.raises(ValueError):
        validate_embeddings(array * 2, 3)


def test_cache_identity_order_and_text():
    assert cache_identity(["a", "b"]) == cache_identity(["a", "b"])
    assert cache_identity(["a", "b"]) != cache_identity(["b", "a"])
    assert cache_identity(["a", "b"]) != cache_identity(["a", "changed"])


def test_metrics_support_macro_and_alignment():
    result = metrics(["A", "A", "B"], ["A", "B", "B"], ["B", "A"])
    assert result["accuracy"] == pytest.approx(2 / 3)
    assert result["macro_f1"] == pytest.approx(2 / 3)
    assert result["weighted_f1"] == pytest.approx(2 / 3)
    assert result["per_class"]["A"]["support"] == 2
    assert result["confusion_matrix"] == [[1, 0], [1, 1]]
    assert metrics([], [], ["A"])["macro_f1"] is None


def test_rules_coverage_and_abstention_no_unknown_correctness():
    result = selective(["A", "UNKNOWN"], np.array(["A", ABSTAIN]), ["A", "UNKNOWN"])
    assert result["coverage"] == 0.5 and result["abstention_rate"] == 0.5
    assert result["retained"]["accuracy"] == 1 and result["correct_over_all_rows"] == 0.5
    rows = [
        {"normalized_counterparty": "Vattenfall Oy", "direction": "OUTGOING"},
        {"normalized_counterparty": "other", "direction": "OUTGOING"},
    ]
    assert list(rule_predictions(rows, "context")) == ["PROPERTY", ABSTAIN]


def test_confusion_matrix_preserves_out_of_cohort_rule_predictions():
    result = metrics(["A", "B", "A"], ["A", "RARE", ABSTAIN], ["A", "B"])
    assert result["confusion_labels"] == ["A", "B", "RARE", ABSTAIN]
    assert sum(map(sum, result["confusion_matrix"])) == result["rows"] == 3
    assert result["macro_f1"] == pytest.approx(1 / 3)
    assert set(result["per_class"]) == {"A", "B"}


@pytest.mark.parametrize("include_structured", [False, True])
def test_tfidf_vocabulary_does_not_learn_from_holdout(include_structured):
    rows = synthetic()
    model = tfidf_pipeline(include_structured).fit(
        feature_rows(rows), [r["confirmed_business_context"] for r in rows]
    )
    features = model["features"]
    text = dict(features.transformer_list)["text"] if include_structured else features
    vocabulary = dict(text["tfidf"].vocabulary_)
    model.predict_proba(feature_rows([{**rows[0], "message": "holdoutuniquetoken"}]))
    assert text["tfidf"].vocabulary_ == vocabulary
    assert "holdoutuniquetoken" not in vocabulary


def test_threshold_boundary_and_hybrid_priority():
    predicted = np.array(["A", "B", "A"])
    confidence = np.array([0.7, 0.69, 0.95])
    assert list(abstain(predicted, confidence, 0.7)) == ["A", ABSTAIN, "A"]
    assert list(hybrid(["B", ABSTAIN, ABSTAIN], predicted, confidence)) == ["B", ABSTAIN, "A"]
    assert selective(["A"], np.array([ABSTAIN]), ["A"])["retained"]["accuracy"] is None


def test_seen_unseen_counts():
    result = seen_analysis(["A", "B"], ["A", "A"], ["known"], ["known", "new"], ["A", "B"])
    assert result["seen_test_fraction"] == 0.5
    assert result["merchant_overlap_count"] == 1
    assert result["seen"]["accuracy"] == 1 and result["unseen"]["accuracy"] == 0


def test_repeated_evaluation_without_row_duplication():
    rows = synthetic()
    before = copy.deepcopy(rows)
    random = np.random.default_rng(42)
    vectors = random.normal(size=(len(rows), DIMENSION))
    a, pa, _, sa = evaluate(rows, vectors)
    b, pb, _, sb = evaluate(rows, vectors)
    assert a == b and sa == sb and rows == before
    assert len(pa) == len(pb)
    assert all(x["predicted"] == y["predicted"] for x, y in zip(pa, pb, strict=True))
    assert MODELS == ("tfidf_text", "tfidf_structured", "e5_text")
    for task in a.values():
        assert task["scored_rows"] == 60
        assert task["grouped_cv"]["test_rows"] == 60
        for model in task["grouped_cv"]["models"].values():
            assert model["merchant_analysis"]["seen_test_fraction"] == 0
        assert task["views"]["grouped"]["merchant_overlap"] == 0
        for split in task["views"].values():
            assert split["train_rows"] + split["test_rows"] == 60


def test_known_merchant_families_do_not_split_aliases():
    for a, b in [
        ("DNA Oyj", "DNA Oyj / prepaid"),
        ("Liikenne ja viestintavirasto", "Liikenne- ja viestintävirasto Traficom"),
        ("Lähitapiola", "Lhitapiola"),
    ]:
        assert merchant({"normalized_counterparty": a}) == merchant({"ultimate_recipient": b})
