"""The gated effect: re-verify the batch against the gate, then upload to Drive.

Fail-closed hash binding: the manifest is rebuilt from CURRENT disk state, so if
any file changed between digest and upload its content hash — and therefore the
gate action_hash — changes, no owner record matches, and the upload is refused.
The cursor advances per uploaded file, never once at the end: a batch killed
mid-flight (the 900s child timeout) keeps every file already uploaded, so the
next tick resumes on the remainder instead of restarting the whole batch. The
gate is still evaluated over the FULL rebuilt manifest — only the upload loop
skips work the cursor already records.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from automation.drive_archive import gate_binding, manifest
from automation.drive_archive.drive_client import DriveArchiveError, DriveClient
from automation.drive_archive.pending import PendingBatch
from automation.drive_archive.routing import route_parts
from automation.interop.external_effect_gate import ApprovalContext


def _append_receipts(path: Path, receipts: list[dict[str, str]]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for receipt in receipts:
            _ = handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    path.chmod(0o600)


def upload_batch(
    pending: PendingBatch,
    *,
    root: Path,
    drive: DriveClient,
    context: ApprovalContext,
    root_folder_name: str,
    cursor_path: Path,
    receipts_path: Path,
    now: Callable[[], datetime] | None = None,
) -> list[dict[str, str]]:
    moment = (now or (lambda: datetime.now(UTC)))().astimezone(UTC)
    try:
        current = manifest.build_manifest(root, pending.project, [entry.path for entry in pending.files])
    except OSError as error:
        raise DriveArchiveError("digest 이후 파일이 변경/삭제됨 — fail-closed") from error

    decision = gate_binding.evaluate(current, context=context)
    if not decision.allowed:
        raise DriveArchiveError(
            f"gate 거부 — 승인 레코드 없음 또는 해시 불일치 (hash={decision.action_hash})"
        )

    cursor = manifest.load_cursor(cursor_path)
    receipts: list[dict[str, str]] = []
    for entry in current.files:
        if cursor.get(entry.path) == entry.sha256:
            continue  # uploaded by an earlier run that died mid-batch
        folder_id = drive.ensure_folder_path(route_parts(root_folder_name, entry.path))
        result = drive.upsert_file(root / entry.path, PurePosixPath(entry.path).name, folder_id)
        receipt = {
            "path": entry.path,
            "file_id": result["id"],
            "web_view_link": result["webViewLink"],
            "action": result["action"],
            "sha256": entry.sha256,
            "timestamp": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        _append_receipts(receipts_path, [receipt])
        manifest.advance_cursor(cursor_path, (entry,))
        receipts.append(receipt)
    return receipts
