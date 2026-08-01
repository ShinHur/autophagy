from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Final


_EXCLUDED_DIRS: Final[tuple[PurePosixPath, ...]] = tuple(
    PurePosixPath(value)
    for value in (
        "docs/qa",
        "docs/patch",
        "docs/troubleshooting",
        "logs",
        ".omo",
        "skills/mail/vendor",
    )
)
_GENERIC_PRIVATE_NAME: Final = re.compile(
    r"(?:ori(?:[0-9a-f]{4,6}|[a-z]{4,6})|tail[a-z0-9]{6,10})",
    re.IGNORECASE,
)
_PREFIX_MAGIC: Final[tuple[tuple[bytes, str], ...]] = (
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"%PDF-", "PDF"),
    (b"SQLite format 3\x00", "SQLite"),
    (b"PK\x03\x04", "ZIP"),
    (b"\x7fELF", "ELF"),
    (b"\x1f\x8b", "gzip"),
)


def excluded_directory(relative: PurePosixPath) -> bool:
    return any(relative == denied or denied in relative.parents for denied in _EXCLUDED_DIRS)


def generic_forbidden_filename(name: str) -> str | None:
    match = _GENERIC_PRIVATE_NAME.search(name)
    return match.group(0) if match is not None else None


def binary_kind(data: bytes) -> str | None:
    for magic, kind in _PREFIX_MAGIC:
        if data.startswith(magic):
            return kind
    if len(data) >= 262 and data[257:262] == b"ustar":
        return "tar"
    return None


def symlink_resolves_outside(root: Path, path: Path) -> bool:
    return not path.resolve(strict=False).is_relative_to(root.resolve(strict=True))
