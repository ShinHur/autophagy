"""Reaction-only watcher specs + no-agent-cron child credential propagation (E11 S7)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from automation.drive_archive import confirm_reaction_watch as watch
from automation.drive_archive.config import APPROVE_EMOJI, CANCEL_EMOJI
from automation.drive_archive.manifest import FileEntry
from automation.drive_archive.pending import PendingBatch, PendingBatchStore
from automation.interop.approval_lease import FileKeyLease
from automation.interop.external_effect_gate import _has_valid_approval
from tests.unit._synthetic import OWNER_ID

OWNER = OWNER_ID
TARGET = "tool:drive_archive_batch_upload:drive_archive.batch_upload"


def _pending(action_hash: str = "sha256:" + "a" * 64, created: str = "2026-07-24T00:00:00Z") -> PendingBatch:
    return PendingBatch(action_hash, TARGET, "msg1", "autophagy", created,
                        (FileEntry("docs/features.md", "b" * 64),))


class FakeTransport:
    def __init__(self, content: str, reactions: dict[str, tuple[tuple[str, bool], ...]]) -> None:
        self._content = content
        self._reactions = reactions
        self.deleted: list[str] = []
        self.dms: list[tuple[str, str]] = []

    def content(self, message_id: str) -> str:
        return self._content

    def reaction_users(self, message_id: str, emoji: str) -> tuple[tuple[str, bool], ...]:
        return self._reactions.get(emoji, ())

    def delete(self, message_id: str) -> None:
        self.deleted.append(message_id)

    def dm(self, owner: str, content: str) -> str:
        self.dms.append((owner, content))
        return "dm1"


class RecordingCommand:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.ran: list[str] = []

    def run(self, pending: PendingBatch) -> bool:
        self.ran.append(pending.action_hash)
        return self.ok


def _watcher(tmp_path, transport, command, now):
    store = PendingBatchStore(tmp_path / "pending")
    watcher = watch.DriveArchiveWatcher(
        store=store, transport=transport, commands=command, owner_id=OWNER,
        approval_log=tmp_path / "approvals.jsonl", now=now,
        lease=FileKeyLease(tmp_path / "leases"),
    )
    return watcher, store


def _at(second: int) -> datetime:
    return datetime(2026, 7, 24, 0, 0, second, tzinfo=UTC)


def test_approved_writes_record_and_runs_upload(tmp_path: Path) -> None:
    pending = _pending()
    transport = FakeTransport(pending.action_hash, {APPROVE_EMOJI: ((OWNER, False),)})
    command = RecordingCommand(ok=True)
    watcher, store = _watcher(tmp_path, transport, command, lambda: _at(30))
    store.put(pending)

    watcher.run_once()

    assert _has_valid_approval(tmp_path / "approvals.jsonl", pending.action_hash, pending.target_id, OWNER, False) is True
    assert command.ran == [pending.action_hash]
    assert store.get(pending.action_hash) is None  # removed after successful upload


def test_cancel_removes_without_record_or_upload(tmp_path: Path) -> None:
    pending = _pending()
    transport = FakeTransport(
        pending.action_hash, {APPROVE_EMOJI: ((OWNER, False),), CANCEL_EMOJI: ((OWNER, False),)}
    )
    command = RecordingCommand()
    watcher, store = _watcher(tmp_path, transport, command, lambda: _at(30))
    store.put(pending)

    watcher.run_once()

    assert command.ran == []  # ⛔ precedence: no upload
    assert store.get(pending.action_hash) is None
    assert not (tmp_path / "approvals.jsonl").exists()  # no approval record on cancel
    assert pending.message_id in transport.deleted


def test_expired_batch_discarded(tmp_path: Path) -> None:
    pending = _pending(created="2026-07-23T00:00:00Z")  # >24h before now
    transport = FakeTransport(pending.action_hash, {APPROVE_EMOJI: ((OWNER, False),)})
    command = RecordingCommand()
    watcher, store = _watcher(tmp_path, transport, command, lambda: datetime(2026, 7, 24, 1, 0, 0, tzinfo=UTC))
    store.put(pending)

    watcher.run_once()

    assert command.ran == []
    assert store.get(pending.action_hash) is None


def test_pending_reaction_retained(tmp_path: Path) -> None:
    pending = _pending()
    transport = FakeTransport(pending.action_hash, {})  # no reactions yet
    command = RecordingCommand()
    watcher, store = _watcher(tmp_path, transport, command, lambda: _at(30))
    store.put(pending)

    watcher.run_once()

    assert command.ran == []
    assert store.get(pending.action_hash) == pending  # retained for a later tick


def test_upload_failure_retains_pending(tmp_path: Path) -> None:
    pending = _pending()
    transport = FakeTransport(pending.action_hash, {APPROVE_EMOJI: ((OWNER, False),)})
    command = RecordingCommand(ok=False)
    watcher, store = _watcher(tmp_path, transport, command, lambda: _at(30))
    store.put(pending)

    watcher.run_once()

    assert command.ran == [pending.action_hash]
    assert store.get(pending.action_hash) == pending  # retried on the next tick


def test_child_receives_token_even_when_parent_env_lacks_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    out = tmp_path / "child-token.txt"
    monkeypatch.setenv("CHILD_OUT", str(out))
    fake_cli = tmp_path / "fake_cli.py"
    fake_cli.write_text(
        "import os\n"
        "open(os.environ['CHILD_OUT'], 'w').write(os.environ.get('DISCORD_BOT_TOKEN', 'MISSING'))\n",
        encoding="utf-8",
    )
    command = watch.CliUploadCommand(cli=fake_cli, token="dummy-cred-42", repo_root=tmp_path)

    assert command.run(_pending()) is True
    assert out.read_text(encoding="utf-8") == "dummy-cred-42"  # (b-2) child got the credential
