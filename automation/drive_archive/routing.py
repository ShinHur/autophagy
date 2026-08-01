"""Keep Drive destinations and approval classes derived from one routing table.

The uploader needs the full Drive folder path while the approval digest needs only
the class name, so both must derive from one table to prevent mismatched messages.
"""

from __future__ import annotations

from pathlib import PurePosixPath

ARCHIVE_CLASSES: tuple[str, ...] = ("plans", "notepads", "features", "qa", "patch", "misc")


def _route(rel: str) -> tuple[str, tuple[str, ...]]:
    """Return the archive class and the sub-folders below it for one repo-relative file."""
    parts = PurePosixPath(rel).parts
    if parts[:2] == (".omo", "plans"):
        return ("plans", parts[2:-1])
    if parts[:2] == (".omo", "notepads"):
        return ("notepads", parts[2:-1])
    if rel == "docs/features.md":
        return ("features", ())
    if parts[:2] == ("docs", "qa"):
        return ("qa", parts[2:-1])
    if parts[:2] == ("docs", "patch"):
        return ("patch", ())
    return ("misc", parts[:-1])


def classify(rel: str) -> str:
    """Name the archive class the approval digest aggregates by."""
    return _route(rel)[0]


def route_parts(root_name: str, rel: str) -> tuple[str, ...]:
    """Return the Drive folder path (root, class, *sub-folders) the file uploads into."""
    archive_class, subdirs = _route(rel)
    return (root_name, archive_class, *subdirs)
