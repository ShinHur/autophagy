"""Hermes cron producer (no_agent, LLM-free) that posts drive-archive digests (E11).

Deployed to ``~/.hermes/scripts/drive_archive_sync_request.py`` and registered as

    hermes cron create "every 1h" --name drive-archive-sync-request \
        --no-agent --script drive_archive_sync_request.py --deliver local

Each tick runs exactly one ``sync_cli request`` pass — it enumerates the changed
in-scope deliverables and POSTS a single batch-approval digest to the surface the
shared approval policy names (with ✅/⛔ pre-attached). It only posts a request;
it never polls or consumes
messages (규약 (a) — the digest producer is not a competing consumer). An empty
change set is a no-op.

No-agent cron contract (docs/guide/watcher-cron-설계규약.md): (b) secrets
self-loaded from ``~/.env.secrets``; (c) repo root on ``sys.path``/``PYTHONPATH``;
single-instance ``flock`` guard.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
import sys
from pathlib import Path
from typing import IO

# Runtime root order (DG-4): AUTOPHAGY_REPO_ROOT override, else the release
# `current` symlink, else the resident mirror. Inlined by value because this
# wrapper sets sys.path BEFORE it can import automation.runtime_root.
def _runtime_root() -> Path:
    override = os.environ.get("AUTOPHAGY_REPO_ROOT", "").strip()
    if override:
        return Path(override)
    current = Path("/srv/autophagy-agent-current")
    return current if current.exists() else Path("/srv/autophagy-agents")


REPO_ROOT = _runtime_root()
SECRETS_PATH = Path.home() / ".env.secrets"
LOCK_PATH = Path.home() / ".hermes" / "drive-archive" / "sync-request.lock"

sys.path.insert(0, str(REPO_ROOT))


def load_secrets(path: Path = SECRETS_PATH) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines from ``~/.env.secrets`` (규약 (b))."""
    secrets: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return secrets
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        secrets[key.strip()] = value.strip().strip('"').strip("'")
    return secrets


def acquire_single_instance_lock(lock_path: Path = LOCK_PATH) -> IO[str] | None:
    """Non-blocking flock; ``None`` = another tick is still running (skip)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def run_request_once() -> int:
    """Run exactly one digest-producing pass via the ``request`` subcommand."""
    environment = load_secrets()
    environment.update(os.environ)
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(REPO_ROOT)
        if existing_pythonpath is None
        else str(REPO_ROOT) + os.pathsep + existing_pythonpath
    )
    completed = subprocess.run(
        [sys.executable, "-m", "automation.drive_archive.sync_cli", "request"],
        env=environment,
        cwd=str(REPO_ROOT),
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    _lock = acquire_single_instance_lock()
    if _lock is None:
        sys.exit(0)
    sys.exit(run_request_once())
