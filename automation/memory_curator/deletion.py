"""Fail-closed disk deletion for one owner-approved memory entry."""

from __future__ import annotations

import fcntl
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from .curator import parse_memory_file, serialize_memory_file
from .model import MemoryEntry, MemoryFile, MemoryKind

_FILENAMES: Final[dict[MemoryKind, str]] = {
    "memory": "MEMORY.md",
    "user": "USER.md",
}
_FILE_MODE: Final = 0o600
_OPEN_SAFELY: Final = os.O_CLOEXEC | os.O_NOFOLLOW


@dataclass(frozen=True, slots=True)
class DeletionOutcome:
    backup_path: Path
    before_chars: int
    after_chars: int


class DeletionError(RuntimeError):
    """Deletion could not satisfy every disk-safety precondition."""


def delete_entry(
    memory_dir: Path,
    kind: MemoryKind,
    index: int,
    *,
    expected_bytes: bytes,
    now: datetime,
) -> DeletionOutcome:
    """Delete exactly one indexed entry while holding Hermes' advisory lock."""
    path = memory_dir / _FILENAMES[kind]

    try:
        path_mode = path.lstat().st_mode
    except OSError as error:
        raise DeletionError(f"memory file is not accessible: {path}") from error
    if stat.S_ISLNK(path_mode):
        raise DeletionError(f"memory file must not be a symlink: {path}")
    if not stat.S_ISREG(path_mode):
        raise DeletionError(f"memory path is not a regular file: {path}")

    lock_path = path.with_name(f"{path.name}.lock")
    lock_flags = os.O_RDWR | _OPEN_SAFELY
    lock_created = False
    try:
        lock_descriptor = os.open(
            lock_path,
            lock_flags | os.O_CREAT | os.O_EXCL,
            _FILE_MODE,
        )
        lock_created = True
    except FileExistsError:
        try:
            lock_descriptor = os.open(lock_path, lock_flags)
        except OSError as error:
            raise DeletionError(f"memory lock is not accessible: {lock_path}") from error
    except OSError as error:
        raise DeletionError(f"memory lock could not be created: {lock_path}") from error

    with os.fdopen(lock_descriptor, "r+b") as lock_file:
        if lock_created:
            os.fchmod(lock_file.fileno(), _FILE_MODE)
        if not stat.S_ISREG(os.fstat(lock_file.fileno()).st_mode):
            raise DeletionError(f"memory lock is not a regular file: {lock_path}")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DeletionError(f"memory lock is already held: {lock_path}") from error
        except OSError as error:
            raise DeletionError(f"memory lock could not be acquired: {lock_path}") from error

        data = _read_regular_file(path)
        if data != expected_bytes:
            raise DeletionError("memory snapshot changed before deletion")
        try:
            original = parse_memory_file(data.decode("utf-8"), kind=kind)
        except UnicodeDecodeError as error:
            raise DeletionError("memory file is not valid UTF-8") from error
        if not 0 <= index < len(original.entries):
            raise DeletionError(f"memory entry index is out of range: {index}")
        removed: MemoryEntry = original.entries[index]

        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        backup_path = path.with_name(f"{path.name}.deleted-{stamp}")
        try:
            backup_descriptor = os.open(
                backup_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_SAFELY,
                _FILE_MODE,
            )
        except FileExistsError as error:
            raise DeletionError(f"deletion backup already exists: {backup_path}") from error
        except OSError as error:
            raise DeletionError(f"deletion backup could not be created: {backup_path}") from error
        try:
            with os.fdopen(backup_descriptor, "wb") as backup_file:
                os.fchmod(backup_file.fileno(), _FILE_MODE)
                _ = backup_file.write(data)
                backup_file.flush()
                os.fsync(backup_file.fileno())
        except OSError as error:
            raise DeletionError(f"deletion backup could not be persisted: {backup_path}") from error

        remaining = original.entries[:index] + original.entries[index + 1 :]
        rewritten = MemoryFile(kind=kind, entries=remaining)
        rewritten_bytes = serialize_memory_file(rewritten).encode("utf-8")
        try:
            temp_descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{path.name}.delete-",
                dir=memory_dir,
            )
        except OSError as error:
            raise DeletionError("temporary deletion file could not be created") from error
        temp_path = Path(temp_name)
        try:
            with os.fdopen(temp_descriptor, "wb") as temp_file:
                _ = temp_file.write(rewritten_bytes)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.chmod(temp_path, _FILE_MODE, follow_symlinks=False)
            os.replace(temp_path, path)
        except OSError as error:
            temp_path.unlink(missing_ok=True)
            raise DeletionError("memory file could not be replaced atomically") from error

        read_back = _read_regular_file(path)
        try:
            verified = parse_memory_file(read_back.decode("utf-8"), kind=kind)
        except UnicodeDecodeError as error:
            raise DeletionError("rewritten memory file is not valid UTF-8") from error
        has_expected_count = len(verified.entries) == len(original.entries) - 1
        removed_is_absent = all(entry.text != removed.text for entry in verified.entries)
        if read_back != rewritten_bytes or not has_expected_count or not removed_is_absent:
            raise DeletionError("rewritten memory file failed deletion verification")

        return DeletionOutcome(
            backup_path=backup_path,
            before_chars=original.char_count,
            after_chars=rewritten.char_count,
        )


def _read_regular_file(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | _OPEN_SAFELY)
    except OSError as error:
        raise DeletionError(f"memory file could not be opened safely: {path}") from error
    try:
        with os.fdopen(descriptor, "rb") as memory_file:
            if not stat.S_ISREG(os.fstat(memory_file.fileno()).st_mode):
                raise DeletionError(f"memory file is no longer regular: {path}")
            return memory_file.read()
    except OSError as error:
        raise DeletionError(f"memory file could not be read: {path}") from error
