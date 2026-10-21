# Repository privacy review

Scope: repository hygiene, verified 2026-10-21. No live model calls, source-data
changes, new UI, dependency changes, scoring changes or history rewriting.

## Findings and redactions

The initial scan covered all 254 tracked files, not just the diff. It examined
meter identifiers, IBAN/bank/BIC values, personal tax/VAT identifiers, customer,
contract and invoice references, email/postal details, source filenames, Gmail
IDs, OAuth secrets and API keys. Private runtime data was not treated as public
content; known source identifiers and credentials were used privately for exact
comparison. Pattern checks supplement that comparison and are not a guarantee
against every possible personal name or address.

- Two real meter identifiers appeared 10 times across five documents. Replaced
  with `<METERING_POINT_CONSUMPTION>` and `<METERING_POINT_PRODUCTION>` in
  `energy_ingestion.md`, `energy_ingestion_review.md`, `ml_experiment_01.md`,
  `ml_experiment_01_review.md` and `ml_experiment_02.md`. The production settlement
  meter remains distinct from the meter used to ingest both energy series.
- Personal local paths were generalized in bank, Gmail and pilot documentation.
  The audit helper now resolves the current user's Downloads directory instead
  of embedding a username; audit/evaluation logic is unchanged.
- Reviewer aliases were generalized in labeling and review-import documentation.
- A synthetic labeling fixture now uses `Example Timber Buyer Oy`; the historical
  bank review uses `<TIMBER_BUYER>`. Stora Enso's existing normalization rule,
  rule-specific test and rule documentation remain because replacing those would
  change behavior or reduce regression coverage. Provider names remain intact.
- The seven IBAN matches are deliberate synthetic redaction fixtures; the email
  fixture uses a reserved example domain. No actual credentials or additional
  known private source identifiers were found. Schema keys, parser field names,
  synthetic document numbers and local-development example credentials are not
  treated as leaked secrets. Historical financial results were not edited.

## Regression protection

`scripts/check_repository_privacy.py` scans all Git-tracked working files by
default, including unchanged files. It checks filenames as well as contents,
reports only filename/line/category and never prints matched values. It detects
Finnish-style 18-digit meter values starting with the country prefix, IBAN-like
values, common OAuth/API secrets, literal credential assignments, Google client
IDs, personal identity patterns, non-example emails and personal home paths.
Exact synthetic IBAN exceptions are restricted to three named test files;
private denylist matches cannot be suppressed by those exceptions.

The optional ignored `.private/privacy_denylist.txt` contains one forbidden value
or specific prefix per line. This local audit populated 470 entries from known
source identifiers and credential values, including the meter prefix. The file
is owner-readable only and must remain untracked and ignored. The script rejects
an unignored or tracked denylist. New nonignored files can be included before
staging; ignored caches/datasets and `.git/` are never traversed by the scanner.

```sh
uv run python scripts/check_repository_privacy.py --include-untracked
# Local stronger check, requiring the private denylist:
uv run python scripts/check_repository_privacy.py --include-untracked --require-denylist
# Committed-byte check (expected to fail until the cleanup is committed):
uv run python scripts/check_repository_privacy.py --revision HEAD --require-denylist
```

The pytest suite includes the whole-repository scan plus synthetic detection,
non-disclosure, private-file exclusion, committed-versus-working-tree, symlink,
filename, denylist and narrow-exception regressions. A public clone without the
private denylist still runs pattern-based checks; it cannot know local private
identifiers that do not match those patterns.

## Git history: exposure remains

All 15 commits reachable from local refs were assessed. The meter identifiers or
specific prefix occur in **14 commits**, including current `HEAD` and **13 earlier
commits**, across **six historical paths**: the five energy/ML documents above and
an older README. This counts snapshots containing the value, not independent
introductions. Remote-only refs, forks and caches were not assessed.

The working tree is redacted; `HEAD`, the index and historical commits have not
been rewritten or committed by this task. A normal cleanup commit will fix the
next tip but leave earlier exposure. The history check found no meter values in
commit messages. `git-filter-repo` is not installed locally and was not run.

### Optional remediation — requires explicit authorization

Coordinate with collaborators and review/commit the clean working tree first.
Do not put the private replacements file or backup in the public repository.
A local owner-only `.private/privacy_history_replacements.txt` has been prepared
with literal consumption/production replacements. It currently addresses the two
meter values; extend it privately for any other historical values to remove.

The following is a procedure for a future authorized operation, **not executed**.
Run from the original repository after the cleanup has been committed. Install
`git-filter-repo` separately if approved; it is not a project dependency.

```sh
# Private backup and separate disposable rewrite clone; do not publish the backup.
umask 077
git bundle create ../tapio-before-privacy.bundle --all
git clone --mirror --no-hardlinks . ../tapio-privacy-rewrite.git
# Supply the actual absolute path locally; do not paste its private contents.
git -C ../tapio-privacy-rewrite.git filter-repo \
  --replace-text /absolute/path/to/Tapio/.private/privacy_history_replacements.txt \
  --replace-message /absolute/path/to/Tapio/.private/privacy_history_replacements.txt
```

Verify every rewritten reachable commit before any push. The original checkout's
scanner can inspect the rewritten clone without copying the denylist into it:

```sh
uv run python - <<'PY'
import subprocess
from pathlib import Path
from scripts.check_repository_privacy import load_denylist, scan_repository

original = Path.cwd()
rewritten = original.parent / "tapio-privacy-rewrite.git"
values = load_denylist(original, Path(".private/privacy_denylist.txt"), required=True)
commits = subprocess.check_output(
    ["git", "-C", str(rewritten), "rev-list", "--all"], text=True
).splitlines()
for commit in commits:
    result = scan_repository(rewritten, values, revision=commit)
    assert not result["findings"], (commit, result["findings"])
    message = subprocess.check_output(
        ["git", "-C", str(rewritten), "show", "-s", "--format=%B", commit], text=True
    )
    assert not any(value in message for value in values), "private commit-message match"
print("All rewritten reachable commits passed")
PY
```

Broader historical findings may require additional replacements; do not waive
those failures. After independent review, record the remote URL and old branch
SHA from the original repository, add the intended remote to the rewritten clone
(`filter-repo` may remove `origin`), and intentionally push each approved branch:

```sh
git -C ../tapio-privacy-rewrite.git remote add publish <REVIEWED_REMOTE_URL>
git -C ../tapio-privacy-rewrite.git push publish \
  --force-with-lease=refs/heads/<BRANCH>:<OLD_REMOTE_SHA> \
  refs/heads/<BRANCH>:refs/heads/<BRANCH>
```

Handle tags and any other affected remote refs explicitly with collaborators;
refresh clones and ask the hosting provider about retained cached views if needed.
Backups, old clones and forks can still contain the values. Meter identifiers are
not authentication secrets and may not be changeable; consult the utility only
if necessary. No actual credential exposure was found requiring rotation here.

## Verification

**858 tests passed**, preserving the prior 837 and adding 21 privacy tests. One
existing Starlette/httpx deprecation warning remains. Ruff check/format, diff
whitespace, dependency lock and all 11 README links passed. The tracked/new-file
privacy scan uses the private denylist. A fresh Alembic schema-comparison result
was not confirmed after the interrupted verification turn. A separate additional
post-test database integrity read was declined; it was not retried. The earlier
read-only source fingerprint check passed for all 14 tables. Migration/model
files are unchanged, and database integration tests passed in disposable schemas.
Final machine-readable checks are retained under ignored
`data/interim/repository_hygiene/`.

The source-table/human-review check above passed; offline verification confirms
the accepted engine/configuration, 66 energy artifacts and holdout/manifest bytes
remain unchanged. Of 1,543 historical protected hashes, two protected
source-file hashes intentionally differ: the synthetic labeling fixture name and
the audit helper's personal-path redaction. The original fingerprint manifests
and historical reports remain untouched; these exceptions are disclosed rather
than rebaselining the historical acceptance. All other protected hashes are checked
unchanged. No claim is made that existing Git history is clean.
