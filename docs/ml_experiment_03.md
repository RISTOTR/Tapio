# Experiment 03 — transaction classification

Protocol fixed before scores: seed 42; no balancing, label changes or search.
The finalized 99 human-reviewed transactions are the only target authority.
Primary context cohort excludes UNKNOWN (98 rows, PERSONAL/PROPERTY/FORESTRY).
Secondary category cohort includes original categories with at least four examples
(95 rows, 10 classes). TIMBER_INCOME 2, TRANSFER 1 and UNKNOWN 1 are excluded from
supervised fitting/scoring and retained for qualitative predictions; SUBSCRIPTION
is absent. Rare categories remain real, not failed taxonomy or balancing targets.

Ordinary evaluation uses one stratified 80/20 holdout. Grouped evaluation uses the
first GroupShuffleSplit 80/20 group holdout at seed 42, without searching seeds or
forcing stratification. Effective merchant prefers a nonempty alphabetic ultimate
recipient, else normalized counterparty; NFKC, case/whitespace/period normalization
and the existing explicit legal-name aliases are applied identically on both sides.
No fuzzy merchant inference. Classes absent from either side are disclosed. Group
and row counts differ because group sizes differ. The pre-score amendment below
adds grouped cross-validation; its folds are not independent evidence.

All model features are allowlisted source fields. Text joins labeled fields with
` | ` separators: normalized_counterparty, ultimate_recipient, message and
transaction_type_code. Missing strings are empty. Structured ablation uses signed
log1p(amount), direction one-hot, month and weekday, scaled from training data only.
UUIDs, both targets, weak suggestions and all human-review metadata are excluded.

Three models are predefined: TF-IDF word unigrams/bigrams with sublinear term
frequency; the same TF-IDF plus structured features; and frozen multilingual E5-small
text embeddings. All use logistic regression C=1, lbfgs, max_iter=2000, tol=1e-4,
class_weight=None. No SMOTE, duplication, synthetic minority rows, resampling,
transformer fine-tuning or test-set hyperparameter selection.

E5-small is chosen for multilingual support (including Finnish), MIT licensing,
local CPU practicality and a 384-dimensional representation. Revision is pinned to
614241f622f53c4eeff9890bdc4f31cfecc418b3. Inputs use `query: ` for classification,
max 512 tokens, L2 normalization, CPU float32 and one torch thread. The model's
[official model card](https://huggingface.co/intfloat/multilingual-e5-small) documents
these conventions. Model downloads send no transaction text; encoding is local.
Only safetensors weights are loaded, with remote code disabled. The cache fingerprint
includes ordered texts, model/revision, prefix, normalization, truncation and stack.

The deterministic baseline reruns bank-rules-1 on source merchant/direction fields,
never reads suggestions as targets or features. UNKNOWN rule output means abstention.
Coverage, agreement on covered rows, overall correct/total (abstention counts wrong)
and abstention are reported for the full reviewed set and each evaluation subset.
Rules predate this evaluation and were designed using this user's bank activity;
they are not a blind externally developed benchmark.

Metrics: accuracy, fixed-task macro F1, weighted F1, per-class precision/recall/F1
with support, aligned confusion matrices, seen/unseen merchant metrics, and aggregate
confusion patterns. Fixed-task macro F1 includes zero-support classes as zero; inspect
support before interpreting grouped or retained-subset scores. No retained rows gives
null metrics. Thresholds .50/.60/.70/.80 are descriptive, not selected by scores.
The hybrid always uses an assigned existing rule, otherwise ML at confidence >=.70,
otherwise NEEDS_REVIEW. It is an evaluation-only simulation. Probabilities are not
claimed calibrated. High covered-rule agreement on this selected sample is not a
confidence guarantee for future rows.

Private outputs under ml/evaluation/output/experiment_03 include cached embeddings,
model downloads, split UUIDs, predictions, errors, excluded-case inspections and
matplotlib plots. Only aggregate summary JSON and documentation may be committed.
No database writes or serving infrastructure are part of this experiment.

Pre-score feasibility amendment: the fixed grouped context holdout contains no
FORESTRY test rows, and the category holdout has GRID_DISTRIBUTION/TAX absent from
training. Retain this holdout, but add one deterministic GroupKFold(n_splits=3)
evaluation. Each eligible row is tested exactly once against unseen merchant groups.
Report pooled out-of-fold metrics, each fold's support and missing classes, plus
macro-F1 mean/std across the three folds. These folds are not independent experiments.
No seed/threshold/model selection uses these scores. Single-merchant categories can
still be absent from training when that merchant is held out; this is a real limitation.

Known grouping families also conservatively combine DNA/prepaid, Traficom spelling
variants, insurer-brand spelling/regional variants and airport kiosk aliases. This
may hold related entities out together; it is safer than counting aliases as unseen.
Source text/features remain unchanged. Arbitrary unknown merchant aliases are not
claimed resolved, and chain branches without an established mapping remain distinct.

## Validation — 2026-10-13

The original `final1` run was reproduced in private directories
`validation_20261013` (cached embeddings) and `validation_refreshed_20261013`
(fresh local encoding with Hugging Face offline mode). Both reproduce summary JSON,
split JSON, predictions, errors and excluded-case predictions exactly after removing
runtime fields. Fresh embeddings have maximum absolute difference **0.0** from the
original cache. No score-based changes to splits, models or thresholds were made.

An independent artifact audit verified source features and labels against the reviewed
CSV, disjoint train/test IDs, zero merchant overlap for every grouped split, and one
out-of-fold prediction per eligible transaction per model. Prediction membership,
confusion-matrix totals, class support, accuracy and coverage at all four thresholds
agree with the saved predictions. Generated outputs remain gitignored.

Validation fixed a confusion-matrix edge case: a rule prediction outside the scored
class list must still appear in the matrix. Fixed-task macro F1 retains its original
class list. This did not change any existing experiment result. Regression tests cover
the edge case and ensure held-out words never enter the fitted TF-IDF vocabulary.

Final checks: **257 tests passed**, including PostgreSQL integration tests after
restarting the stopped local database runtime. Ruff lint/format checks, dependency
lockfile validation and `git diff --check` passed.

Fixed-task macro F1 (pooled out-of-fold values for grouped CV):

| Target | Model | Ordinary | Grouped holdout | Grouped CV |
| --- | --- | ---: | ---: | ---: |
| Context | TF-IDF text | 0.6344 | 0.2632 | 0.2747 |
| Context | TF-IDF + structured | 0.2745 | 0.2476 | 0.3410 |
| Context | E5 text | 0.2745 | 0.2632 | 0.2754 |
| Category | TF-IDF text | 0.5394 | 0.0533 | 0.0618 |
| Category | TF-IDF + structured | 0.2333 | 0.0571 | 0.0597 |
| Category | E5 text | 0.0593 | 0.0533 | 0.0613 |

The ordinary splits each share 10 merchant groups between train and test. Their
stronger TF-IDF results do not establish generalization to new merchants. Grouped
category performance is weak across all representations. ELECTRICITY,
GRID_DISTRIBUTION, INSURANCE and TAX each have only one merchant group, so grouped
evaluation necessarily tests some categories absent from training. The context
holdout has no FORESTRY examples; pooled grouped CV provides broader coverage but
still has only 98 rows. Category scoring has 95 rows, with OTHER accounting for 42.

At confidence 0.70, grouped-CV category coverage is 7.4% for TF-IDF text, 10.5% for
TF-IDF plus structured features and 0% for E5. E5's hybrid category coverage of 23.2%
comes entirely from existing rules. These results support continued human review;
they do not validate unattended classification or calibrated confidence thresholds.
