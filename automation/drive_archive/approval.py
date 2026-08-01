"""Write the ``manual_reaction`` approval record the production gate accepts.

The payload schema is byte-compatible with
``external_effect_gate._has_valid_approval``: ``action=external_effect.approval``,
``approval.method=manual_reaction``, ``approval.channel=approvals``,
``result={"status":"approved"}``, matching ``hash``/``target_id``/``owner_id``.

``approval.channel`` is that schema's constant — the literal the gate matches on,
shared verbatim by every flow whatever surface it posts on — not a statement about
which Discord surface the digest was posted to. Where a digest lives is the
binding on the pending batch, and only that.
"""

from __future__ import annotations

import fcntl
import json
from datetime import UTC, datetime
from pathlib import Path

from automation.drive_archive.pending import PendingBatch


def write_manual_reaction(
    approval_log: Path, pending: PendingBatch, owner_id: str, *, now: datetime | None = None
) -> None:
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    payload = {
        "action": "external_effect.approval",
        "approval": {
            "channel": "approvals",
            "message_id": pending.message_id,
            "method": "manual_reaction",
            "owner_id": owner_id,
        },
        "hash": pending.action_hash,
        "result": {"status": "approved"},
        "target_id": pending.target_id,
        "timestamp": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    approval_log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with approval_log.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        _ = handle.write(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        )
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    approval_log.chmod(0o600)
