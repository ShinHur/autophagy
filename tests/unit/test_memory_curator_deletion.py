from __future__ import annotations

import fcntl
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from automation.memory_curator.curator import parse_memory_file
from automation.memory_curator.deletion import DeletionError, delete_entry

ORIGINAL: Final = b"first entry\n\xc2\xa7\nsecond entry\n\xc2\xa7\nthird entry"
NOW: Final = datetime(2026, 7, 30, 12, 34, 56, tzinfo=UTC)
BACKUP_NAME: Final = "MEMORY.md.deleted-20260730T123456Z"


def test_delete_entry_when_index_is_valid_preserves_order_and_exact_backup(
    tmp_path: Path,
) -> None:
    # Given: a three-entry memory file and its exact planning snapshot.
    memory_path = tmp_path / "MEMORY.md"
    _ = memory_path.write_bytes(ORIGINAL)

    # When: the middle entry is deleted by its validated index.
    outcome = delete_entry(
        tmp_path,
        "memory",
        1,
        expected_bytes=ORIGINAL,
        now=NOW,
    )

    # Then: only the middle entry is gone and the original bytes are recoverable.
    rewritten = memory_path.read_text(encoding="utf-8")
    parsed = parse_memory_file(rewritten, kind="memory")
    original = parse_memory_file(ORIGINAL.decode(), kind="memory")
    assert tuple(entry.text for entry in parsed.entries) == (
        "first entry",
        "third entry",
    )
    assert rewritten == "first entry\n§\nthird entry"
    assert len(parsed.entries) == 2
    assert outcome.backup_path == tmp_path / BACKUP_NAME
    assert outcome.backup_path.read_bytes() == ORIGINAL
    assert stat.S_IMODE(outcome.backup_path.stat().st_mode) == 0o600
    assert outcome.before_chars == original.char_count
    assert outcome.after_chars == parsed.char_count
    assert outcome.after_chars < outcome.before_chars


def test_delete_entry_when_snapshot_drifted_mutates_nothing(tmp_path: Path) -> None:
    # Given: disk bytes that differ from the caller's stale planning snapshot.
    memory_path = tmp_path / "MEMORY.md"
    _ = memory_path.write_bytes(ORIGINAL)

    # When: deletion re-verifies the stale snapshot under its lock.
    with pytest.raises(DeletionError):
        _ = delete_entry(
            tmp_path,
            "memory",
            1,
            expected_bytes=b"stale snapshot",
            now=NOW,
        )

    # Then: neither the memory nor a deletion backup was mutated.
    assert memory_path.read_bytes() == ORIGINAL
    assert list(tmp_path.glob("MEMORY.md.deleted-*")) == []


def test_delete_entry_when_memory_path_is_symlink_never_follows_it(
    tmp_path: Path,
) -> None:
    # Given: MEMORY.md is a symlink to an otherwise valid target.
    target = tmp_path / "target.md"
    _ = target.write_bytes(ORIGINAL)
    memory_path = tmp_path / "MEMORY.md"
    memory_path.symlink_to(target.name)

    # When: deletion validates the disk path.
    with pytest.raises(DeletionError):
        _ = delete_entry(
            tmp_path,
            "memory",
            1,
            expected_bytes=ORIGINAL,
            now=NOW,
        )

    # Then: the symlink and its target remain untouched.
    assert memory_path.is_symlink()
    assert target.read_bytes() == ORIGINAL
    assert list(tmp_path.glob("MEMORY.md.deleted-*")) == []


@pytest.mark.parametrize("index", [5, -1])
def test_delete_entry_when_index_is_out_of_range_mutates_nothing(
    tmp_path: Path,
    index: int,
) -> None:
    # Given: a three-entry memory file and an invalid positional index.
    memory_path = tmp_path / "MEMORY.md"
    _ = memory_path.write_bytes(ORIGINAL)

    # When: deletion validates the index after re-reading the snapshot.
    with pytest.raises(DeletionError):
        _ = delete_entry(
            tmp_path,
            "memory",
            index,
            expected_bytes=ORIGINAL,
            now=NOW,
        )

    # Then: no destructive write or backup occurs.
    assert memory_path.read_bytes() == ORIGINAL
    assert list(tmp_path.glob("MEMORY.md.deleted-*")) == []


def test_delete_entry_when_lock_is_contended_fails_without_waiting(
    tmp_path: Path,
) -> None:
    # Given: another writer holds Hermes' sibling advisory lock.
    memory_path = tmp_path / "MEMORY.md"
    _ = memory_path.write_bytes(ORIGINAL)
    lock_path = tmp_path / "MEMORY.md.lock"
    with lock_path.open("a+b") as lock_file:
        lock_path.chmod(0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

        # When: deletion attempts a non-blocking exclusive lock.
        with pytest.raises(DeletionError):
            _ = delete_entry(
                tmp_path,
                "memory",
                1,
                expected_bytes=ORIGINAL,
                now=NOW,
            )

    # Then: contention did not mutate the memory or create a backup.
    assert memory_path.read_bytes() == ORIGINAL
    assert list(tmp_path.glob("MEMORY.md.deleted-*")) == []


def test_delete_entry_when_backup_name_collides_never_overwrites_it(
    tmp_path: Path,
) -> None:
    # Given: the permanent backup name for this timestamp already exists.
    memory_path = tmp_path / "MEMORY.md"
    _ = memory_path.write_bytes(ORIGINAL)
    backup_path = tmp_path / BACKUP_NAME
    _ = backup_path.write_bytes(b"existing backup")

    # When: deletion reaches the backup creation step.
    with pytest.raises(DeletionError):
        _ = delete_entry(
            tmp_path,
            "memory",
            1,
            expected_bytes=ORIGINAL,
            now=NOW,
        )

    # Then: neither the source nor the colliding backup is overwritten.
    assert memory_path.read_bytes() == ORIGINAL
    assert backup_path.read_bytes() == b"existing backup"
