"""Approval-record specs: the record we write is accepted by the REAL gate (E11 S3).

This is the cross-module security regression — if the production
``_has_valid_approval`` schema drifts, these break.
"""

from __future__ import annotations

from pathlib import Path

from automation.drive_archive import approval, gate_binding, manifest
from automation.drive_archive.manifest import FileEntry
from automation.drive_archive.pending import PendingBatch
from automation.interop.external_effect_gate import ApprovalContext, _has_valid_approval
from tests.unit._synthetic import OWNER_ID

OWNER = OWNER_ID
TARGET = "tool:drive_archive_batch_upload:drive_archive.batch_upload"


def _pending(action_hash: str) -> PendingBatch:
    return PendingBatch(
        action_hash=action_hash,
        target_id=TARGET,
        message_id="msg1",
        project="autophagy",
        created_at="2026-07-24T00:00:00Z",
        files=(FileEntry("docs/features.md", "b" * 64),),
    )


def test_manual_reaction_record_accepted_by_real_gate(tmp_path: Path) -> None:
    log = tmp_path / "approvals.jsonl"
    pending = _pending("sha256:" + "a" * 64)
    approval.write_manual_reaction(log, pending, OWNER)

    assert _has_valid_approval(log, pending.action_hash, pending.target_id, OWNER, False) is True
    # wrong hash / owner / target must all fail closed
    assert _has_valid_approval(log, "sha256:" + "z" * 64, pending.target_id, OWNER, False) is False
    assert _has_valid_approval(log, pending.action_hash, pending.target_id, "other", False) is False
    assert _has_valid_approval(log, pending.action_hash, "tool:other:x", OWNER, False) is False


def test_full_gate_roundtrip_allows_after_manual_reaction(tmp_path: Path) -> None:
    built = manifest.BatchManifest("autophagy", (FileEntry("docs/features.md", "b" * 64),))
    log = tmp_path / "approvals.jsonl"
    ctx = ApprovalContext(approval_log=log, owner_id=OWNER, e2e_test_mode=False)

    before = gate_binding.evaluate(built, context=ctx)
    assert before.external_effect is True
    assert before.allowed is False

    pending = PendingBatch(
        action_hash=before.action_hash,
        target_id=before.target_id,
        message_id="msg",
        project="autophagy",
        created_at="2026-07-24T00:00:00Z",
        files=built.files,
    )
    approval.write_manual_reaction(log, pending, OWNER)

    after = gate_binding.evaluate(built, context=ctx)
    assert after.allowed is True
