"""Runtime state locations for drive-archive, all OUTSIDE the tracked checkout.

The seed/checkout guard mirrors ``triage_mode._runtime_path_shadows_seed``:
writing runtime state into the checkout dirties the ops tree and blocks
``git pull --ff-only`` / peer-attest sync, so a state dir at or inside the repo
fails closed.
"""

from __future__ import annotations

import os
from pathlib import Path


class DriveArchivePathError(RuntimeError):
    """Runtime state dir could not be resolved safely (fail closed)."""


def repo_root() -> Path:
    env = os.environ.get("AUTOPHAGY_REPO_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _shadows_checkout(path: Path, root: Path) -> bool:
    try:
        resolved = path.expanduser().resolve()
        resolved_root = root.resolve()
    except OSError:
        return True
    return resolved == resolved_root or resolved_root in resolved.parents


def state_dir() -> Path:
    path = Path(os.environ.get("DRIVE_ARCHIVE_STATE_DIR", "~/.hermes/drive-archive")).expanduser()
    if _shadows_checkout(path, repo_root()):
        raise DriveArchivePathError(
            f"drive-archive 런타임 상태는 체크아웃 밖이어야 합니다 (fail-closed): {path}"
        )
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def approval_log() -> Path:
    override = os.environ.get("DRIVE_ARCHIVE_APPROVAL_LOG")
    return Path(override).expanduser() if override else state_dir() / "approvals.jsonl"


def cursor_file() -> Path:
    return state_dir() / "cursor.json"


def pending_dir() -> Path:
    path = state_dir() / "pending"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def approval_lease_dir() -> Path:
    return state_dir() / "approval-leases"


def posting_journal_dir() -> Path:
    return state_dir() / "posting-journal"


def folders_cache() -> Path:
    return state_dir() / "folders.json"


def receipts_log() -> Path:
    return state_dir() / "receipts.jsonl"
