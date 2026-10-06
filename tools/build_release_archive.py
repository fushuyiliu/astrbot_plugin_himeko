"""Build a deterministic public-source archive from an explicit allowlist.

Example:
    python tools/build_release_archive.py . path-to-output.zip
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

ROOT_FILES = frozenset(
    {
        ".gitattributes",
        ".gitignore",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "NOTICE.md",
        "README.en.md",
        "README.md",
        "SECURITY.md",
        "__init__.py",
        "_conf_schema.json",
        "attachments.py",
        "main.py",
        "metadata.yaml",
        "pyproject.toml",
        "reminders.py",
        "requirements-ocr.txt",
        "requirements.txt",
        "storage.py",
    }
)
ALLOWED_DIRECTORIES = frozenset({"tests", "tools"})
ALLOWED_SUFFIXES = frozenset({".md", ".py", ".json", ".txt"})


def archive_members(root: Path) -> list[Path]:
    """Return exactly the public source files approved for the archive."""
    members: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if len(relative.parts) == 1:
            if relative.name in ROOT_FILES:
                members.append(path)
            continue
        if relative.parts[0] in ALLOWED_DIRECTORIES and path.suffix in ALLOWED_SUFFIXES:
            members.append(path)
    return members


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.release_root.resolve()
    output = args.output.resolve()
    if not root.is_dir():
        parser.error("release_root must be an existing directory")
    if output.is_relative_to(root):
        parser.error("output must be outside release_root")
    members = archive_members(root)
    expected_roots = {"metadata.yaml", "main.py", "README.md", "LICENSE"}
    if not expected_roots.issubset({path.name for path in members}):
        parser.error("release root is missing required public files")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in members:
            archive.write(path, path.relative_to(root).as_posix())
    print(f"archive-members: {len(members)}")
    print(f"archive: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
