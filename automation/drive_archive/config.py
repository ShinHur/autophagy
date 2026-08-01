"""Shared owner/channel config reads for drive-archive (leaf module, no siblings).

Mirrors the interop-config resolution used by ``budget_confirm`` /
``procure_review`` so the whole feature agrees on owner identity.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APPROVE_EMOJI = "\u2705"  # white check mark
CANCEL_EMOJI = "\u26d4"  # no entry


class DriveArchiveConfigError(RuntimeError):
    """Interop config is unreadable or missing a required field (fail closed)."""


def interop_config_path() -> Path:
    return Path(os.environ.get("INTEROP_CONFIG", "~/.hermes/interop/config.json")).expanduser()


def config_value(key: str) -> str | None:
    try:
        value = json.loads(interop_config_path().read_text(encoding="utf-8")).get(key)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, str) and value else None


def owner_id() -> str:
    owner = config_value("owner_id")
    if owner is None:
        raise DriveArchiveConfigError("interop config에 owner_id가 없습니다 (fail-closed)")
    return owner
