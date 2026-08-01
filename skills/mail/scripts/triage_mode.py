"""Mail-mode resolution + W4-2-runtime re-verdict (3-state: no-go|read-go|full-go).

The repo verdict is the tracked immutable SEED (configs/mail-mode.default.json,
source W0-7c). The runtime re-verdict lives OUTSIDE the checkout at
~/.hermes/mail-triage/mail-mode.json: two consecutive approved-send failures
write it with ``source: W4-2-runtime`` and append a W4-1N switch record. The
runtime file wins over the seed; anything unreadable resolves to no-go (fail
closed). A runtime path at or beside the seed fails closed to no-go and is
never written into the checkout. Restoring full-go is a human/orchestrator
action (delete or rewrite the runtime file), never automatic.
"""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

import triage_core
import site_mail_backend

MODES = ("no-go", "read-go", "full-go")


def gate_dir() -> Path:
    path = Path(os.environ.get("TRIAGE_GATE_DIR", "~/.hermes/mail-triage")).expanduser()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def runtime_mode_file() -> Path:
    return Path(
        os.environ.get("TRIAGE_MAIL_MODE_FILE", str(gate_dir() / "mail-mode.json"))
    ).expanduser()


def repo_mode_file() -> Path:
    override = os.environ.get("TRIAGE_MAIL_MODE_REPO")
    if override:
        return Path(override).expanduser()
    config_env = site_mail_backend._config_env()
    try:
        return config_env.deploy_root() / "configs" / "mail-mode.default.json"
    except config_env.ConfigError:
        return gate_dir() / "unconfigured-seed" / "mail-mode.default.json"


def _runtime_path_shadows_seed(runtime: Path, seed: Path) -> bool:
    """Fail-closed: the runtime override must never live at (or beside) the
    tracked seed — writing there dirties the ops checkout and blocks pulls."""
    try:
        resolved_runtime = runtime.expanduser().resolve()
        resolved_seed = seed.expanduser().resolve()
    except OSError:
        return True
    return resolved_runtime == resolved_seed or resolved_runtime.parent == resolved_seed.parent


def effective_mode() -> str:
    """Runtime re-verdict wins over the repo verdict; missing both = no-go."""
    runtime, seed = runtime_mode_file(), repo_mode_file()
    if _runtime_path_shadows_seed(runtime, seed):
        return "no-go"
    for path in (runtime, seed):
        try:
            mode = json.loads(path.read_text(encoding="utf-8")).get("mode")
        except (OSError, json.JSONDecodeError):
            continue
        if mode in MODES:
            return str(mode)
    return "no-go"


def downgrade_to_no_go(reason: str) -> None:
    """W4-2-runtime re-verdict + W4-1N switch record (2 consecutive failures)."""
    previous = effective_mode()
    runtime, seed = runtime_mode_file(), repo_mode_file()
    if not _runtime_path_shadows_seed(runtime, seed):
        write_json(runtime, {
            "decided_at": triage_core.utc_now(),
            "mode": "no-go",
            "source": "W4-2-runtime",
        })
    append_record(gate_dir() / "mode-switch.jsonl", {
        "event": "w4-1n-switch",
        "from": previous,
        "reason": triage_core.redact(reason)[:300],
        "source": "W4-2-runtime",
        "timestamp": triage_core.utc_now(),
        "to": "no-go",
    })


def append_record(path: Path, record: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    path.chmod(0o600)


def write_json(path: Path, record: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)
