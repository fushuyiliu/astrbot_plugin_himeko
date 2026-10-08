"""Fail closed on public-release privacy findings without printing matched text.

Usage:
    python tools/audit_public_release.py .
    python tools/audit_public_release.py . --history C:\\path\\to\\private-source

The optional history scan reports only category, commit prefix, and path. It
never prints the matching line, a credential, or file content.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Rule:
    category: str
    pattern: re.Pattern[str]


RULES = (
    Rule(
        "private_key_material",
        re.compile(r"-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----", re.I),
    ),
    Rule("cloud_access_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    Rule("model_or_api_secret", re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")),
    Rule(
        "credential_assignment",
        re.compile(
            r"(?i)(?:[\"']?(?:api[_ -]?key|access[_ -]?key|secret|token|password)[\"']?)\s*[:=]\s*"
            r"[\"']?(?!<|\$\{|YOUR_|REPLACE_|example|changeme)[^\s\"']{8,}"
        ),
    ),
    Rule(
        "absolute_user_or_drive_path",
        re.compile(r"(?i)(?:[a-z]:\\|/(?:home|users)/)"),
    ),
    Rule(
        "personal_workspace_marker",
        re.compile(r"个人分身|Obsidian|wechat-private-bot|qq-group-bot"),
    ),
    Rule("fixed_private_adapter", re.compile(r"weixin_oc_user_id|wechat-private")),
    Rule(
        "raw_ipv4_address",
        re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
    ),
    Rule(
        "email_address",
        re.compile(
            r"(?i)\b[A-Z0-9._%+-]+@(?!users\.noreply\.github\.com\b)"
            r"[A-Z0-9.-]+\.[A-Z]{2,}\b"
        ),
    ),
)
FORBIDDEN_NAMES = re.compile(
    r"(?i)(?:^|[._-])(?:\.env|id_rsa|.*\.pem|.*\.key|local\.settings\.json)$"
)
TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".txt",
    ".toml",
    ".ps1",
    ".sh",
    ".ini",
}
SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", ".validation-venv"}
AUDITOR_RELATIVE_PATH = "tools/audit_public_release.py"


def categories_in_text(text: str) -> set[str]:
    return {rule.category for rule in RULES if rule.pattern.search(text)}


def release_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.relative_to(root).as_posix() == AUDITOR_RELATIVE_PATH:
            # The scanner necessarily contains the patterns it is designed to
            # detect. Its own source is exercised through the test suite.
            continue
        yield path


def scan_tree(root: Path) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for path in release_files(root):
        relative = path.relative_to(root).as_posix()
        if FORBIDDEN_NAMES.search(path.name):
            findings.append(("forbidden_filename", relative))
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append(("non_utf8_text_file", relative))
            continue
        for category in sorted(categories_in_text(text)):
            findings.append((category, relative))
    return sorted(set(findings))


def git_output(repo: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout


def scan_history(repo: Path) -> list[tuple[str, str, str]]:
    """Scan every reachable blob but expose only category, commit prefix, and path."""
    findings: set[tuple[str, str, str]] = set()
    commits = [value for value in git_output(repo, ["rev-list", "--all"]).splitlines() if value]
    for commit in commits:
        for path in git_output(repo, ["ls-tree", "-r", "--name-only", commit]).splitlines():
            if path == AUDITOR_RELATIVE_PATH:
                continue
            if FORBIDDEN_NAMES.search(Path(path).name):
                findings.add(("forbidden_filename", commit[:12], path))
            if Path(path).suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = git_output(repo, ["show", f"{commit}:{path}"])
            except subprocess.CalledProcessError:
                continue
            for category in categories_in_text(text):
                findings.add((category, commit[:12], path))
    return sorted(findings)


def print_findings(title: str, findings: list[tuple[str, ...]]) -> None:
    print(f"{title}: {len(findings)} finding(s)")
    for finding in findings:
        print(" | ".join(finding))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_root", type=Path)
    parser.add_argument("--history", type=Path, help="Optional private source repository to scan")
    args = parser.parse_args()
    root = args.release_root.resolve()
    if not root.is_dir():
        parser.error("release_root must be an existing directory")
    tree_findings = scan_tree(root)
    print_findings("public-tree", tree_findings)
    history_findings: list[tuple[str, str, str]] = []
    if args.history:
        history = args.history.resolve()
        try:
            history_findings = scan_history(history)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"history-scan-error: {type(exc).__name__}", file=sys.stderr)
            return 2
        print_findings("private-history", history_findings)
    return 1 if tree_findings or history_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
