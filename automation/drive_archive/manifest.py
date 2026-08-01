"""Content-hash batch manifest + upload cursor for drive-archive.

The manifest is the canonical identity a batch approval binds to: the gate's
``action_hash`` is computed over ``to_arguments()`` (files sorted by path, each
with its sha256), so any content change between digest and upload changes the
hash and invalidates the owner record (fail closed).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from automation.interop.external_effect_gate import JsonValue


@dataclass(frozen=True, slots=True)
class FileEntry:
    """One in-scope file with its current content hash (hex sha256)."""

    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class BatchManifest:
    """The set of files a single batch approval authorizes uploading."""

    project: str
    files: tuple[FileEntry, ...]

    def to_arguments(self) -> dict[str, JsonValue]:
        ordered = sorted(self.files, key=lambda entry: entry.path)
        return {
            "project": self.project,
            "files": [{"path": entry.path, "sha256": entry.sha256} for entry in ordered],
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root: Path, project: str, rel_paths: Iterable[str]) -> BatchManifest:
    entries = tuple(
        FileEntry(path=rel, sha256=sha256_file(root / rel))
        for rel in sorted(rel_paths)
    )
    return BatchManifest(project=project, files=entries)


def diff(manifest: BatchManifest, cursor: dict[str, str]) -> BatchManifest:
    """Keep only files whose current hash differs from the last uploaded hash."""
    changed = tuple(
        entry for entry in manifest.files if cursor.get(entry.path) != entry.sha256
    )
    return BatchManifest(project=manifest.project, files=changed)


def load_cursor(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): str(value) for key, value in data.items()}


def advance_cursor(path: Path, files: tuple[FileEntry, ...]) -> None:
    cursor = load_cursor(path)
    for entry in files:
        cursor[entry.path] = entry.sha256
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(cursor, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)
