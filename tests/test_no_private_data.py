"""Guard against committing private or sensitive data.

Scans every file that git would track (tracked files plus untracked files that
are not ignored) for private network addresses, MAC addresses, personal email
addresses and credential-looking strings. Examples and fixtures must use the
ranges reserved for documentation (RFC 5737) and example domains (RFC 2606).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Binary or generated files that are not worth scanning.
SKIPPED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2"}

OCTET = r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"

PATTERNS: dict[str, re.Pattern[str]] = {
    "private IPv4 address (10/8)": re.compile(
        rf"(?<![\d.])10\.{OCTET}\.{OCTET}\.{OCTET}(?![\d.])"
    ),
    "private IPv4 address (172.16/12)": re.compile(
        rf"(?<![\d.])172\.(?:1[6-9]|2\d|3[01])\.{OCTET}\.{OCTET}(?![\d.])"
    ),
    "private IPv4 address (192.168/16)": re.compile(
        rf"(?<![\d.])192\.168\.{OCTET}\.{OCTET}(?![\d.])"
    ),
    "MAC address": re.compile(
        r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}(?![0-9A-Fa-f:-])"
    ),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    "GitHub fine-grained token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "JSON Web Token": re.compile(
        r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    ),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}

# Email addresses that are safe to publish.
ALLOWED_EMAIL_SUFFIXES = (
    "@users.noreply.github.com",
    "@example.com",
    "@example.org",
    "@example.net",
)


def _candidate_files() -> list[Path]:
    """Return files git tracks or would track (respects .gitignore)."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    files = []
    for line in result.stdout.splitlines():
        path = REPO_ROOT / line
        if path.is_file() and path.suffix.lower() not in SKIPPED_SUFFIXES:
            files.append(path)
    return files


# The network Home Assistant Supervisor uses for apps (add-ons). It is the
# same on every Home Assistant OS installation, so it identifies nobody.
ALLOWED_ADDRESSES = ("172.30.32.0",)


def _is_allowed(kind: str, match: str) -> bool:
    if kind == "email address":
        return match.lower().endswith(ALLOWED_EMAIL_SUFFIXES)
    if kind.startswith("private IPv4 address"):
        return match in ALLOWED_ADDRESSES
    return False


def find_private_data() -> list[str]:
    """Return a human-readable finding for every match in the repository."""
    findings: list[str] = []
    for path in _candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in PATTERNS.items():
                for match in pattern.finditer(line):
                    if _is_allowed(kind, match.group(0)):
                        continue
                    relative = path.relative_to(REPO_ROOT).as_posix()
                    findings.append(f"{relative}:{line_number}: {kind}")
    return findings


def test_repository_contains_no_private_data() -> None:
    findings = find_private_data()
    assert not findings, "Private data found:\n" + "\n".join(findings)


def test_scanner_detects_known_patterns() -> None:
    """The patterns themselves must work, otherwise the guard is worthless."""
    samples = {
        "private IPv4 address (10/8)": ".".join(["10", "1", "2", "3"]),
        "private IPv4 address (172.16/12)": ".".join(["172", "20", "0", "5"]),
        "private IPv4 address (192.168/16)": ".".join(["192", "168", "1", "1"]),
        "MAC address": ":".join(["AA", "BB", "CC", "00", "11", "22"]),
        "email address": "someone" + "@" + "mail.test",
        "GitHub token": "ghp" + "_" + "a" * 36,
    }
    for kind, sample in samples.items():
        assert PATTERNS[kind].search(sample), kind

    # Documentation ranges and public resolvers must not be flagged.
    for harmless in ("192.0.2.10", "198.51.100.7", "203.0.113.1", "1.1.1.1"):
        for kind, pattern in PATTERNS.items():
            assert not pattern.search(harmless), (kind, harmless)
