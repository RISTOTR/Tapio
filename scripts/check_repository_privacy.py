"""Scan Git-listed working files, or a committed tree; never print matched values."""

import argparse
import json
import re
import subprocess
from pathlib import Path

PATTERNS = {
    "FINNISH_METERING_POINT": re.compile(r"(?<!\w)643(?:[ -]?\d){15}(?!\w)"),
    "IBAN_LIKE": re.compile(r"\b[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){11,30}\b"),
    "OAUTH_OR_API_SECRET": re.compile(
        r"(?:GOCSPX-[\w-]{10,}|ya29\.[\w.-]{15,}|sk-(?:proj-)?[\w-]{20,}|1//[\w-]{20,}"
        r"|AIza[\w-]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
    ),
    "LITERAL_CREDENTIAL": re.compile(
        r"""(?i)["']?(?:client_secret|access_token|refresh_token|api_key)["']?\s*[:=]\s*["'][A-Za-z0-9_./+-]{20,}["']"""
    ),
    "GOOGLE_CLIENT_ID": re.compile(r"\b\d{8,}-[\w-]+\.apps\.googleusercontent\.com\b"),
    "FINNISH_PERSONAL_ID": re.compile(r"\b\d{6}[-+ABCDEFUVWXY]\d{3}[0-9A-Y]\b"),
    "PERSONAL_HOME_PATH": re.compile(r"/(?:Users|home)/(?!example(?:/|\b))[^/\s\"']+"),
    "EMAIL_ADDRESS": re.compile(r"\b[\w.+-]+@([\w.-]+\.[A-Za-z]{2,})\b"),
}

# Exact, deliberately synthetic IBAN fixtures used to test redaction. No blanket test exemption.
SYNTHETIC_IBANS = {
    "apps/api/tests/test_phase05_database.py": {"FI00" + "12345678901234"},
    "apps/api/tests/test_pilot.py": {"FI21" + "12345600000785"},
    "apps/api/tests/test_transaction_labels.py": {"FI12 " + "1234 1234 1234 12"},
}


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def load_denylist(root, path, required=False):
    path = path if path.is_absolute() else root / path
    if not path.exists():
        if required:
            raise ValueError("PRIVATE_DENYLIST_MISSING")
        return []
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError("DENYLIST_MUST_BE_INSIDE_IGNORED_REPOSITORY_PATH") from None
    tracked = git(root, "ls-files", "--", relative.as_posix())
    ignored = (
        subprocess.run(
            ["git", "-C", str(root), "check-ignore", "--quiet", str(relative)],
            capture_output=True,
        ).returncode
        == 0
    )
    if tracked or not ignored:
        raise ValueError("DENYLIST_MUST_BE_UNTRACKED_AND_IGNORED")
    return [
        v for line in path.read_text().splitlines() if (v := line.strip()) and not v.startswith("#")
    ]


def scan_text(name, content, denylist=()):
    findings = []
    for number, line in enumerate(content.splitlines(), 1):
        # Match literal values/prefixes, including whitespace-formatted source identifiers.
        compact = re.sub(r"\s+", "", line).casefold()
        if any(re.sub(r"\s+", "", value).casefold() in compact for value in denylist):
            findings.append({"file": name, "line": number, "category": "PRIVATE_DENYLIST"})
        for category, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                if category == "IBAN_LIKE" and match.group() in SYNTHETIC_IBANS.get(name, set()):
                    continue
                if category == "EMAIL_ADDRESS" and (
                    match.group(1).endswith((".invalid", ".example"))
                    or match.group(1) in {"example.com", "example.org", "example.net"}
                ):
                    continue
                findings.append({"file": name, "line": number, "category": category})
                break
    return findings


def scan_repository(root, denylist=(), revision=None, include_untracked=False):
    if revision and include_untracked:
        raise ValueError("REVISION_AND_UNTRACKED_ARE_EXCLUSIVE")
    if revision:
        names = git(root, "ls-tree", "-rz", "--name-only", revision).split(b"\0")
    else:
        names = git(root, "ls-files", "-z", "--cached").split(b"\0")
        if include_untracked:
            names += git(root, "ls-files", "-z", "--others", "--exclude-standard").split(b"\0")
    findings = []
    count = 0
    for raw in sorted(set(names) - {b""}):
        name = raw.decode("utf-8", errors="surrogateescape")
        path = root / name
        # Scan names too: a raw source filename can itself disclose an identifier.
        name_hits = scan_text("[redacted filename]", name, denylist)
        findings.extend(name_hits)
        display = "[redacted filename]" if name_hits else name
        if revision:
            content = git(root, "show", f"{revision}:{name}")
        elif path.is_symlink():
            findings.append({"file": display, "line": 0, "category": "SYMLINK_REQUIRES_REVIEW"})
            continue
        elif path.is_file():
            content = path.read_bytes()
        else:
            continue  # Working-tree deletion: committed contents remain covered by --revision.
        count += 1
        findings.extend(scan_text(display, content.decode("utf-8", errors="replace"), denylist))
    return {"files_scanned": count, "findings": findings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--denylist", type=Path, default=Path(".private/privacy_denylist.txt"))
    parser.add_argument("--require-denylist", action="store_true")
    parser.add_argument(
        "--revision", help="Scan committed bytes, e.g. HEAD, instead of working files"
    )
    parser.add_argument(
        "--include-untracked", action="store_true", help="Also scan nonignored new files"
    )
    args = parser.parse_args()
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").decode().strip())
        denylist = load_denylist(root, args.denylist, args.require_denylist)
        report = scan_repository(root, denylist, args.revision, args.include_untracked)
        report["private_denylist_loaded"] = bool(denylist)
        print(json.dumps(report, indent=2))
        return int(bool(report["findings"]))
    except (ValueError, OSError, subprocess.CalledProcessError):
        print(json.dumps({"error": "PRIVACY_SCAN_CONFIGURATION_OR_READ_FAILURE"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
