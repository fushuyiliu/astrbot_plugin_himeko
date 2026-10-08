"""Synthetic Git-history checks for the public plugin release audit."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDITOR = ROOT / "tools" / "audit_public_release.py"


class PublicReleaseAuditTests(unittest.TestCase):
    """Exercise the command-line gate against throwaway Git repositories."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "candidate"
        self.git("init", "-b", "main", str(self.repo), cwd=self.repo.parent)
        self.git("config", "user.name", "Audit Fixture")
        self.git("config", "user.email", self.fixture_email())
        self.write("tools/audit_public_release.py", AUDITOR.read_text(encoding="utf-8"))
        self.write("README.md", "clean public candidate\n")
        self.commit("initial clean candidate")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def fixture_email() -> str:
        return "audit" + "@" + "example" + ".invalid"

    @staticmethod
    def secret_value() -> str:
        return "s" + "k-" + "abcdefghijklmnop"

    def git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed

    def write(self, relative: str, text: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str) -> None:
        self.git("add", "--", ".")
        self.git("commit", "-m", message)

    def audit(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(AUDITOR), str(self.repo), "--history", str(self.repo)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_clean_history_exits_zero_and_skips_auditor_source(self) -> None:
        result = self.audit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("public-tree: 0 finding(s)", result.stdout)
        self.assertIn("private-history: 0 finding(s)", result.stdout)

    def test_deleted_secret_in_history_fails_without_echoing_content(self) -> None:
        sample = self.secret_value()
        self.write("removed.txt", sample + "\n")
        self.commit("add synthetic secret")
        (self.repo / "removed.txt").unlink()
        self.commit("remove synthetic secret")
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("model_or_api_secret", result.stdout)
        self.assertNotIn(sample, result.stdout + result.stderr)

    def test_deleted_forbidden_filename_in_history_fails_closed(self) -> None:
        forbidden = "." + "env"
        self.write(forbidden, "fictional value\n")
        self.commit("add forbidden filename")
        (self.repo / forbidden).unlink()
        self.commit("remove forbidden filename")
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("forbidden_filename", result.stdout)
        self.assertIn(forbidden, result.stdout)

    def test_current_tree_finding_fails_closed(self) -> None:
        self.write("current.txt", self.secret_value() + "\n")
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("model_or_api_secret", result.stdout)

    @staticmethod
    def json_credential(key: str) -> str:
        return json.dumps({key: "fictional-" + key + "-value"}) + "\n"

    def test_current_json_credentials_fail_without_echoing_content(self) -> None:
        for key in ("password", "api_key"):
            with self.subTest(key=key):
                content = self.json_credential(key)
                self.write("current.json", content)
                result = self.audit()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("credential_assignment", result.stdout)
                self.assertNotIn(content.strip(), result.stdout + result.stderr)
                (self.repo / "current.json").unlink()

    def test_deleted_json_credentials_in_history_fail_without_echoing_content(self) -> None:
        for key in ("password", "api_key"):
            with self.subTest(key=key):
                content = self.json_credential(key)
                path = self.repo / "removed.json"
                path.write_text(content, encoding="utf-8")
                self.commit("add synthetic JSON credential")
                path.unlink()
                self.commit("remove synthetic JSON credential")
                result = self.audit()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("credential_assignment", result.stdout)
                self.assertNotIn(content.strip(), result.stdout + result.stderr)

    def test_json_placeholder_remains_allowed(self) -> None:
        self.write("placeholder.json", json.dumps({"api_key": "YOUR_" + "API_KEY"}) + "\n")
        result = self.audit()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_yaml_toml_and_python_credentials_fail_closed(self) -> None:
        for filename, key, separator in (
            ("settings.yaml", "token", ": "),
            ("settings.toml", "secret", " = "),
            ("settings.py", "access_key", " = "),
        ):
            with self.subTest(filename=filename):
                content = key + separator + '"fictional-' + key + '-value"\n'
                self.write(filename, content)
                result = self.audit()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("credential_assignment", result.stdout)
                self.assertNotIn(content.strip(), result.stdout + result.stderr)
                (self.repo / filename).unlink()


if __name__ == "__main__":
    unittest.main()
