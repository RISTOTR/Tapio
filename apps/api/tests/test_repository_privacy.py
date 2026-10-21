"""Synthetic privacy regressions; never embed real private identifiers."""

import json
import subprocess
from pathlib import Path

import pytest

from scripts.check_repository_privacy import load_denylist, scan_repository, scan_text


@pytest.mark.parametrize(
    "value,category",
    [
        ("643" + "012345678901234", "FINNISH_METERING_POINT"),
        ("643 " + "01234 56789 01234", "FINNISH_METERING_POINT"),
        ("FI99" + "12345678901234", "IBAN_LIKE"),
        ("DE99 " + "1234 5678 9012 3456 78", "IBAN_LIKE"),
        ("GOCSPX-" + "x" * 25, "OAUTH_OR_API_SECRET"),
        ("ya29." + "x" * 25, "OAUTH_OR_API_SECRET"),
        ("1//" + "x" * 25, "OAUTH_OR_API_SECRET"),
        ("sk-proj-" + "x" * 25, "OAUTH_OR_API_SECRET"),
        ('"refresh_token": "' + "x" * 25 + '"', "LITERAL_CREDENTIAL"),
        ("123456789-" + "x" * 20 + ".apps.googleusercontent.com", "GOOGLE_CLIENT_ID"),
        ("010199" + "-123A", "FINNISH_PERSONAL_ID"),
        ("private" + "@person.test", "EMAIL_ADDRESS"),
        ("/Users/" + "synthetic-person/document", "PERSONAL_HOME_PATH"),
    ],
)
def test_patterns_and_non_disclosing_report(value, category):
    result = scan_text("example.md", "heading\n" + value)
    assert category in {r["category"] for r in result}
    assert all(r["line"] == 2 for r in result)
    assert value not in json.dumps(result)


def test_exact_and_prefix_denylist_with_spacing():
    assert scan_text("a", "custom-private-123", ["custom-private-"])
    assert scan_text("a", "CUST OM-123", ["CUSTOM-123"])
    assert not scan_text("a", "custom-public-123", ["custom-private-"])


def test_synthetic_exceptions_are_narrow_and_denylist_overrides():
    value = "FI00" + "12345678901234"
    name = "apps/api/tests/test_phase05_database.py"
    assert not scan_text(name, value)
    assert scan_text("docs/example.md", value)
    assert scan_text(name, value, [value])[0]["category"] == "PRIVATE_DENYLIST"
    assert scan_text(name, "FI99" + "12345678901234")


def test_placeholders_and_reserved_email_are_safe():
    assert not scan_text("a", "<METERING_POINT_CONSUMPTION> <METERING_POINT_PRODUCTION>")
    assert not scan_text("a", "utility@example.invalid client_secret access_token")


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".private/\n")
    (tmp_path / "tracked.md").write_text("original safe content")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "synthetic",
        ],
        check=True,
    )
    (tmp_path / ".private").mkdir()
    return tmp_path


def test_tracked_scan_excludes_private_and_detects_unchanged_index_file(repo):
    secret = "private-fixture-value"
    (repo / ".private" / "secret").write_text(secret)
    (repo / "new.md").write_text(secret)
    assert not scan_repository(repo, [secret])["findings"]
    assert scan_repository(repo, [secret], include_untracked=True)["findings"]
    (repo / "tracked.md").write_text(secret)
    assert scan_repository(repo, [secret])["findings"]
    assert not scan_repository(repo, [secret], revision="HEAD")["findings"]


def test_private_denylist_is_optional_or_required_and_cannot_be_published(repo):
    path = Path(".private/denylist.txt")
    assert load_denylist(repo, path) == []
    with pytest.raises(ValueError):
        load_denylist(repo, path, required=True)
    (repo / path).write_text("# comment\nsynthetic-secret\n")
    assert load_denylist(repo, path, required=True) == ["synthetic-secret"]
    with pytest.raises(ValueError):
        load_denylist(repo, Path("tracked.md"))


def test_sensitive_filename_is_redacted(repo):
    (repo / "private-prefix-123.txt").write_text("safe")
    result = scan_repository(repo, ["private-prefix-"], include_untracked=True)
    assert result["findings"][0]["file"] == "[redacted filename]"
    assert "private-prefix-" not in json.dumps(result)


def test_symlink_is_not_followed(repo):
    (repo / "new.md").symlink_to(repo / ".private")
    result = scan_repository(repo, include_untracked=True)
    assert result["findings"][0]["category"] == "SYMLINK_REQUIRES_REVIEW"


def test_repository_privacy_regression():
    root = Path(__file__).resolve().parents[3]
    denylist = load_denylist(root, Path(".private/privacy_denylist.txt"))
    assert scan_repository(root, denylist, include_untracked=True)["findings"] == []
