"""Small, local-only persistence helpers for the public Himeko plugin.

This module deliberately knows nothing about the host filesystem beyond the
directory provided by the plugin.  It must not grow a fallback to a user's
home, profile, knowledge-base, or project directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))


def now() -> datetime:
    """Return a timezone-aware Shanghai timestamp."""
    return datetime.now(TZ)


def digest(value: str) -> str:
    """Return a stable SHA-256 digest for an opaque local identifier."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def atomic_json(path: Path, value: object) -> None:
    """Write JSON atomically without leaving a partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def search_terms(query: str) -> dict[str, str]:
    """Return bounded literal search terms without reading any host directory."""
    text = str(query or "").strip().lower()
    if len(text) < 2:
        return {}
    terms: dict[str, str] = {}
    for word in re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text):
        terms[word] = "literal"
        if len(word) >= 4 and all("\u4e00" <= char <= "\u9fff" for char in word):
            for index in range(len(word) - 1):
                terms.setdefault(word[index : index + 2], "fragment")
    return dict(list(terms.items())[:24])
