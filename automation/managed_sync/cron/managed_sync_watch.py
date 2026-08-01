"""Hermes cron watcher (no_agent, LLM-free) for the managed-skill sync pipeline (MS-S6).

Deployed to ``~/.hermes/scripts/managed_sync_watch.py`` and registered as

    hermes cron create "every 30m" --name managed-sync-watch \
        --no-agent --script managed_sync_watch.py --deliver local

Git-polling manual indexer (rag-ingest-watch class, 규약 (a) 예외): each tick
runs exactly one ``sync`` subcommand pass — fetch, verify, and quarantine
only. Owner-gated steps stay owner-gated: this wrapper never invokes any
other subcommand and never passes any extra flag. It polls a pre-approved
git remote, nothing else.

No-agent cron contract (docs/guide/watcher-cron-설계규약.md):
- (b) secrets are self-loaded from ``~/.env.secrets`` (system env wins);
- (b-2) the child subprocess receives credentials via an explicit ``env=``;
- (c) the repo root (``AUTOPHAGY_REPO_ROOT``) is inserted into ``sys.path``
  and exported as ``PYTHONPATH`` so ``automation.*`` imports resolve;
- single-instance ``flock`` guard — an overlapping tick exits 0 silently.
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
LOCK_PATH = Path.home() / ".hermes" / "managed-sync" / "watch.lock"

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


def run_sync_once() -> int:
    """Run exactly one fetch/verify/quarantine pass via the ``sync`` subcommand."""
    environment = load_secrets()
    environment.update(os.environ)
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(REPO_ROOT)
        if existing_pythonpath is None
        else str(REPO_ROOT) + os.pathsep + existing_pythonpath
    )
    completed = subprocess.run(
        [sys.executable, "-m", "automation.managed_sync", "sync"],
        env=environment,
        cwd=str(REPO_ROOT),
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    _lock = acquire_single_instance_lock()
    if _lock is None:
        sys.exit(0)
    sys.exit(run_sync_once())
