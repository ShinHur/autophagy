"""Resumable-upload regression: a killed batch keeps its progress (E11 900s-timeout loop).

Prod symptom locked here: 361 files could not finish inside the child's 900s
timeout, progress was persisted only after the whole loop, so every tick
restarted the batch from zero and the watcher died on the escaping
``TimeoutExpired`` — starving a second pending batch as well.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from automation.drive_archive import approval, gate_binding, manifest, uploader
from automation.drive_archive import confirm_reaction_watch as watch
from automation.drive_archive.config import APPROVE_EMOJI
from automation.drive_archive.drive_client import DriveArchiveError, DriveClient
from automation.drive_archive.manifest import FileEntry
from automation.drive_archive.pending import PendingBatch, PendingBatchStore
from automation.interop.external_effect_gate import ApprovalContext, JsonValue
from tests.unit._synthetic import OWNER_ID

OWNER = OWNER_ID
TARGET = "tool:drive_archive_batch_upload:drive_archive.batch_upload"
FIRST = ".omo/plans/a.md"
SECOND = ".omo/plans/b.md"
THIRD = "docs/features.md"


class FakeGws:
    """Minimal in-memory gws: nothing pre-exists, so every file takes the +upload path."""

    def __init__(self, root: Path, fail_on: str | None = None) -> None:
        self._root: Path = root
        self._fail_on: str | None = fail_on
        self._n: int = 0
        self.uploaded: list[str] = []

    def __call__(self, argv: list[str]) -> dict[str, JsonValue]:
        self._n += 1
        if argv[2] == "+upload":
            rel = Path(argv[3]).relative_to(self._root).as_posix()
            if rel == self._fail_on:
                raise DriveArchiveError(f"gws 업로드 실패(모의): {rel}")  # stands in for the kill
            self.uploaded.append(rel)
            return {"id": f"file{self._n}"}
        responses: dict[str, dict[str, JsonValue]] = {
            "list": {"files": []},
            "create": {"id": f"fold{self._n}"},
            "get": {"webViewLink": f"https://drive.google.com/file/d/f{self._n}/view"},
        }
        try:
            return responses[argv[3]]
        except KeyError as error:
            raise AssertionError(argv) from error


def _drive(tmp_path: Path, root: Path, fail_on: str | None = None) -> tuple[DriveClient, FakeGws]:
    fake = FakeGws(root, fail_on)
    return DriveClient("gws", tmp_path / "folders.json", runner=fake), fake


def _seed_repo(root: Path) -> list[str]:
    (root / ".omo" / "plans").mkdir(parents=True)
    (root / ".omo" / "plans" / "a.md").write_text("plan A", encoding="utf-8")
    (root / ".omo" / "plans" / "b.md").write_text("plan B", encoding="utf-8")
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "features.md").write_text("feat", encoding="utf-8")
    return [FIRST, SECOND, THIRD]


def _approved_batch(
    root: Path, log: Path
) -> tuple[manifest.BatchManifest, ApprovalContext, PendingBatch]:
    """Owner-approve the FULL three-file batch (one action_hash over all of it)."""
    root.mkdir()
    built = manifest.build_manifest(root, "autophagy", _seed_repo(root))
    ctx = ApprovalContext(approval_log=log, owner_id=OWNER, e2e_test_mode=False)
    decision = gate_binding.evaluate(built, context=ctx)
    pending = PendingBatch(
        decision.action_hash, decision.target_id, "msg", "autophagy",
        "2026-07-24T00:00:00Z", built.files,
    )
    approval.write_manual_reaction(log, pending, OWNER)
    return built, ctx, pending


def _run(pending: PendingBatch, root: Path, drive: DriveClient, ctx: ApprovalContext,
         tmp_path: Path) -> list[dict[str, str]]:
    return uploader.upload_batch(
        pending, root=root, drive=drive, context=ctx, root_folder_name="Archive",
        cursor_path=tmp_path / "cursor.json", receipts_path=tmp_path / "receipts.jsonl",
    )


def _receipt_paths(tmp_path: Path) -> list[str]:
    text = (tmp_path / "receipts.jsonl").read_text(encoding="utf-8")
    return [json.loads(line)["path"] for line in text.splitlines() if line]


def test_failure_midway_keeps_uploaded_entries_in_cursor_and_receipts(tmp_path: Path) -> None:
    """Given a batch that dies on file 2, Then file 1 stays recorded (not lost)."""
    root = tmp_path / "repo"
    built, ctx, pending = _approved_batch(root, tmp_path / "approvals.jsonl")
    drive, fake = _drive(tmp_path, root, fail_on=SECOND)

    with pytest.raises(DriveArchiveError):
        _run(pending, root, drive, ctx, tmp_path)

    assert fake.uploaded == [FIRST]  # third never attempted
    assert manifest.load_cursor(tmp_path / "cursor.json") == {FIRST: built.files[0].sha256}
    assert _receipt_paths(tmp_path) == [FIRST]


def test_rerun_after_partial_failure_uploads_only_the_remainder(tmp_path: Path) -> None:
    """Given persisted partial progress, When re-run, Then only files 2-3 are uploaded."""
    root = tmp_path / "repo"
    built, ctx, pending = _approved_batch(root, tmp_path / "approvals.jsonl")
    with pytest.raises(DriveArchiveError):
        _run(pending, root, _drive(tmp_path, root, fail_on=SECOND)[0], ctx, tmp_path)

    resumed, fake = _drive(tmp_path, root)
    receipts = _run(pending, root, resumed, ctx, tmp_path)

    assert fake.uploaded == [SECOND, THIRD]  # file 1 not re-uploaded
    assert [receipt["path"] for receipt in receipts] == [SECOND, THIRD]
    assert _receipt_paths(tmp_path) == [FIRST, SECOND, THIRD]
    cursor = manifest.load_cursor(tmp_path / "cursor.json")
    assert manifest.diff(built, cursor).files == ()  # batch complete


def test_resume_still_binds_the_full_batch_hash(tmp_path: Path) -> None:
    """The resumed run is authorized by the FULL-batch action_hash, not a remainder hash."""
    root = tmp_path / "repo"
    built, ctx, pending = _approved_batch(root, tmp_path / "approvals.jsonl")
    manifest.advance_cursor(tmp_path / "cursor.json", built.files[:1])  # file 1 already done

    receipts = _run(pending, root, _drive(tmp_path, root)[0], ctx, tmp_path)

    remainder = manifest.BatchManifest(project=built.project, files=built.files[1:])
    assert gate_binding.evaluate(remainder, context=ctx).action_hash != pending.action_hash
    assert [receipt["path"] for receipt in receipts] == [SECOND, THIRD]


def test_gate_refusal_uploads_nothing_even_with_partial_cursor(tmp_path: Path) -> None:
    """The skip loop never bypasses the gate: no approval ⇒ fail-closed, zero uploads."""
    root = tmp_path / "repo"
    root.mkdir()
    built = manifest.build_manifest(root, "autophagy", _seed_repo(root))
    ctx = ApprovalContext(
        approval_log=tmp_path / "approvals.jsonl", owner_id=OWNER, e2e_test_mode=False
    )
    decision = gate_binding.evaluate(built, context=ctx)
    pending = PendingBatch(
        decision.action_hash, decision.target_id, "msg", "autophagy",
        "2026-07-24T00:00:00Z", built.files,
    )
    manifest.advance_cursor(tmp_path / "cursor.json", built.files[:1])
    drive, fake = _drive(tmp_path, root)

    with pytest.raises(DriveArchiveError):
        _run(pending, root, drive, ctx, tmp_path)

    assert fake.uploaded == []
    assert not (tmp_path / "receipts.jsonl").exists()


def test_child_timeout_returns_false_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child that outlives the timeout must not kill the cron tick."""
    monkeypatch.setattr(watch, "UPLOAD_TIMEOUT_SECONDS", 1)
    slow_cli = tmp_path / "slow_cli.py"
    slow_cli.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    command = watch.CliUploadCommand(cli=slow_cli, token="dummy-cred-42", repo_root=tmp_path)
    pending = PendingBatch(
        "sha256:" + "a" * 64, TARGET, "msg1", "autophagy", "2026-07-24T00:00:00Z",
        (FileEntry(THIRD, "b" * 64),),
    )

    assert command.run(pending) is False



class _TwoBatchTransport:
    """Both digests carry their own action_hash and a bound owner ✅."""

    def __init__(self, contents: dict[str, str]) -> None:
        self._contents = contents
        self.deleted: list[str] = []
        self.dms: list[tuple[str, str]] = []

    def content(self, message_id: str) -> str:
        return self._contents[message_id]

    def reaction_users(self, message_id: str, emoji: str) -> tuple[tuple[str, bool], ...]:
        return ((OWNER, False),) if emoji == APPROVE_EMOJI else ()

    def delete(self, message_id: str) -> None:
        self.deleted.append(message_id)

    def dm(self, owner: str, content: str) -> str:
        self.dms.append((owner, content))
        return "dm1"


class _ExplodingCommand:
    """Raises for one batch (as an escaping TimeoutExpired used to), succeeds for the rest."""

    def __init__(self, fail_hash: str) -> None:
        self._fail_hash = fail_hash
        self.ran: list[str] = []

    def run(self, pending: PendingBatch) -> bool:
        self.ran.append(pending.action_hash)
        if pending.action_hash == self._fail_hash:
            raise subprocess.TimeoutExpired(cmd="sync_cli.py", timeout=900)
        return True


def _batch(action_hash: str, message_id: str) -> PendingBatch:
    return PendingBatch(
        action_hash, TARGET, message_id, "autophagy", "2026-07-24T00:00:00Z",
        (FileEntry(THIRD, "b" * 64),),
    )


def test_failing_batch_does_not_starve_the_next_batch(tmp_path: Path) -> None:
    """Given two pending batches and a crash on the first, Then the second still runs."""
    failing = _batch("sha256:" + "a" * 64, "msg-a")
    healthy = _batch("sha256:" + "c" * 64, "msg-c")
    transport = _TwoBatchTransport({"msg-a": failing.action_hash, "msg-c": healthy.action_hash})
    command = _ExplodingCommand(fail_hash=failing.action_hash)
    store = PendingBatchStore(tmp_path / "pending")
    store.put(failing)
    store.put(healthy)
    watcher = watch.DriveArchiveWatcher(
        store=store, transport=transport, commands=command, owner_id=OWNER,
        approval_log=tmp_path / "approvals.jsonl",
        now=lambda: datetime(2026, 7, 24, 0, 0, 30, tzinfo=UTC),
        lease=watch.FileKeyLease(tmp_path / "leases"),
    )

    watcher.run_once()

    assert command.ran == [failing.action_hash, healthy.action_hash]
    assert store.get(failing.action_hash) == failing  # fail-closed: retried next tick
    assert store.get(healthy.action_hash) is None  # completed and removed
