"""drive-archive CLI: plan | request | upload --hash | status.

``request`` routes producer concurrency through the shared approval lifecycle;
``upload`` is the gated effect the reaction watcher runs after a bound ✅. All
steps read the cursor/pending/approval state from outside the checkout.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from typing import assert_never

from automation.drive_archive import (
    approval_adapter,
    config,
    discord,
    drive_client,
    gate_binding,
    manifest,
    paths,
    pending,
    request_output,
    scope,
    uploader,
)
from automation.interop.approval_lease import FileKeyLease, PostingJournal
from automation.interop.approval_lifecycle import (
    ApprovalIntent,
    request_owner_approval,
)

DEFAULT_PROJECT = "autophagy-agents"
DEFAULT_ROOT_FOLDER = "Autophagy 문서아카이브"


def project_name() -> str:
    return os.environ.get("DRIVE_ARCHIVE_PROJECT", DEFAULT_PROJECT)


def root_folder_name() -> str:
    return os.environ.get("DRIVE_ARCHIVE_ROOT_NAME", DEFAULT_ROOT_FOLDER)


@dataclass(frozen=True, slots=True)
class ChangedBatch:
    """The changed files plus the cursor keys they are diffed against (one cursor read)."""

    batch: manifest.BatchManifest
    tracked: frozenset[str]


def _changed_batch() -> ChangedBatch:
    root = paths.repo_root()
    full = manifest.build_manifest(root, project_name(), scope.enumerate_scope(root))
    cursor = manifest.load_cursor(paths.cursor_file())
    return ChangedBatch(batch=manifest.diff(full, cursor), tracked=frozenset(cursor))


def cmd_plan() -> int:
    changed = _changed_batch()
    for entry in changed.batch.files:
        print(f"{entry.sha256[:12]}  {entry.path}")
    print(f"PLAN files={len(changed.batch.files)}")
    return 0


def cmd_request() -> int:
    changed = _changed_batch()
    if not changed.batch.files:
        print("NO-CHANGES")
        return 0
    decision = gate_binding.evaluate(changed.batch)
    store = pending.PendingBatchStore(paths.pending_dir())
    transport = discord.configured_approvals()
    match transport:
        case discord.DiscordApprovals(channel_id=channel_id):
            pass
        case discord.StubApprovals():
            channel_id = "stub"
        case unreachable:
            assert_never(unreachable)
    key = approval_adapter.approval_key(changed.batch.project)
    intent = ApprovalIntent(key=key, action_hash=decision.action_hash, channel_id=channel_id)
    gate = approval_adapter.DriveApprovalGate(
        store=store,
        transport=transport,
        owner_id=config.owner_id(),
        channel_id=channel_id,
        payload=approval_adapter.DriveApprovalPayload(
            batch=changed.batch,
            target_id=decision.target_id,
            root_name=root_folder_name(),
            tracked=changed.tracked,
        ),
    )
    verdict = request_owner_approval(
        intent,
        gate,
        FileKeyLease(paths.approval_lease_dir()),
        PostingJournal(paths.posting_journal_dir()),
    )
    return request_output.print_report(
        request_output.RequestReport(
            verdict=verdict,
            intent=intent,
            gate=gate,
            file_count=len(changed.batch.files),
        )
    )


def cmd_upload(action_hash: str) -> int:
    store = pending.PendingBatchStore(paths.pending_dir())
    record = store.get(action_hash)
    if record is None:
        print(f"UPLOAD-REFUSED reason=unknown-hash hash={action_hash}")
        return 1
    client = drive_client.DriveClient(
        gws_bin=os.environ.get("DRIVE_ARCHIVE_GWS_BIN", "gws"),
        folder_cache=paths.folders_cache(),
    )
    try:
        receipts = uploader.upload_batch(
            record,
            root=paths.repo_root(),
            drive=client,
            context=gate_binding.approval_context(),
            root_folder_name=root_folder_name(),
            cursor_path=paths.cursor_file(),
            receipts_path=paths.receipts_log(),
        )
    except drive_client.DriveArchiveError as error:
        print(f"UPLOAD-REFUSED reason=fail-closed hash={action_hash} detail={error}")
        return 1
    _notify_owner(record, receipts)
    store.remove(action_hash)
    print(f"SYNC-UPLOADED hash={action_hash} files={len(receipts)}")
    return 0


def cmd_status() -> int:
    store = pending.PendingBatchStore(paths.pending_dir())
    pendings = store.all()
    tracked = manifest.load_cursor(paths.cursor_file())
    print(f"STATUS pending={len(pendings)} tracked={len(tracked)}")
    for record in pendings:
        print(f"- hash={record.action_hash} files={len(record.files)} message={record.message_id}")
    return 0


def _notify_owner(record: pending.PendingBatch, receipts: list[dict[str, str]]) -> None:
    lines = [f"✅ Drive 아카이브 업로드 완료 — {len(receipts)}건 (project {record.project})"]
    lines.extend(f"- {receipt['path']}: {receipt['web_view_link']}" for receipt in receipts[:20])
    try:
        discord.configured_approvals().dm(config.owner_id(), "\n".join(lines))
    except (discord.DiscordError, config.DriveArchiveConfigError, OSError) as error:
        print(f"NOTIFY-SKIPPED detail={error}")  # upload already succeeded — notify is best-effort


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="drive_archive", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="show the changed in-scope files (no external effect)")
    sub.add_parser("request", help="post a batch-approval digest to the owner's approval surface")
    upload = sub.add_parser("upload", help="gated upload of an approved batch")
    upload.add_argument("--hash", required=True, dest="action_hash")
    sub.add_parser("status", help="show pending batches + tracked file count")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    match args.command:
        case "plan":
            return cmd_plan()
        case "request":
            return cmd_request()
        case "upload":
            return cmd_upload(args.action_hash)
        case "status":
            return cmd_status()
        case unreachable:
            assert_never(unreachable)


if __name__ == "__main__":
    raise SystemExit(main())
