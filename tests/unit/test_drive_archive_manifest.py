"""Unit specs for drive-archive scope enumeration + content-hash manifest (E11 S1)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from automation.drive_archive import manifest, scope


def _mk(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_enumerate_scope_covers_classes_and_excludes_source(tmp_path: Path) -> None:
    _mk(tmp_path, ".omo/plans/autophagy-agents.md", "a")
    _mk(tmp_path, ".omo/plans/archive/old.md", "b")
    _mk(tmp_path, ".omo/notepads/slug/decisions.md", "c")
    _mk(tmp_path, "docs/features.md", "d")
    _mk(tmp_path, "docs/qa/E11/00-note.txt", "e")
    _mk(tmp_path, "docs/patch/2026-07-24-x.md", "f")
    _mk(tmp_path, "automation/drive_archive/scope.py", "print()")  # source: excluded
    _mk(tmp_path, "docs/guide/whatever.md", "g")  # not an in-scope class: excluded

    found = scope.enumerate_scope(tmp_path)

    assert ".omo/plans/autophagy-agents.md" in found
    assert ".omo/plans/archive/old.md" in found
    assert ".omo/notepads/slug/decisions.md" in found
    assert "docs/features.md" in found
    assert "docs/qa/E11/00-note.txt" in found
    assert "docs/patch/2026-07-24-x.md" in found
    assert "automation/drive_archive/scope.py" not in found
    assert "docs/guide/whatever.md" not in found
    assert list(found) == sorted(found)  # deterministic ordering


def test_build_manifest_hashes_and_diffs(tmp_path: Path) -> None:
    _mk(tmp_path, ".omo/plans/a.md", "hello")
    _mk(tmp_path, "docs/features.md", "world")
    rels = scope.enumerate_scope(tmp_path)

    built = manifest.build_manifest(tmp_path, "autophagy", rels)
    assert built.project == "autophagy"
    assert {entry.path for entry in built.files} == set(rels)

    expected = hashlib.sha256(b"hello").hexdigest()
    entry = next(e for e in built.files if e.path == ".omo/plans/a.md")
    assert entry.sha256 == expected

    cursor = {e.path: e.sha256 for e in built.files}
    assert manifest.diff(built, cursor).files == ()  # nothing changed

    cursor[".omo/plans/a.md"] = "0" * 64  # simulate stale/never-uploaded
    changed = manifest.diff(built, cursor)
    assert [e.path for e in changed.files] == [".omo/plans/a.md"]


def test_to_arguments_is_sorted_and_canonical() -> None:
    built = manifest.BatchManifest(
        "p", (manifest.FileEntry("z.md", "h2"), manifest.FileEntry("a.md", "h1"))
    )
    args = built.to_arguments()
    assert args["project"] == "p"
    assert [f["path"] for f in args["files"]] == ["a.md", "z.md"]
    assert [f["sha256"] for f in args["files"]] == ["h1", "h2"]


def test_cursor_roundtrip_and_advance(tmp_path: Path) -> None:
    cursor_path = tmp_path / "cursor.json"
    assert manifest.load_cursor(cursor_path) == {}

    manifest.advance_cursor(cursor_path, (manifest.FileEntry("a.md", "h1"),))
    assert manifest.load_cursor(cursor_path) == {"a.md": "h1"}

    manifest.advance_cursor(
        cursor_path, (manifest.FileEntry("a.md", "h2"), manifest.FileEntry("b.md", "h3"))
    )
    assert manifest.load_cursor(cursor_path) == {"a.md": "h2", "b.md": "h3"}
