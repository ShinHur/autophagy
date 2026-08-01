"""Producer keeps exactly ONE live approval message per project (E11 supersede).

Observed: the hourly ``request`` tick posted the same digest three times
(17:15 / 18:16 / 19:17, identical ``action_hash``) because it always posts while a
batch awaits ✅. ``PendingBatchStore.put()`` then overwrites ``message_id``, so the
owner's ✅ on an older message is silently orphaned — the approval never binds.
These tests lock the invariant: exactly one live approval message per project, and
the producer never drops a batch the watcher has claimed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from automation.drive_archive import approval_adapter, config, paths, pending, sync_cli
from automation.drive_archive.discord import StubApprovals
from automation.interop.approval_lease import FileKeyLease
from tests.unit._synthetic import OWNER_ID

OWNER = OWNER_ID
REQUESTED = re.compile(r"SYNC-REQUESTED hash=(\S+) files=(\d+) message=(\S+)")


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    (repo / ".omo" / "plans").mkdir(parents=True)
    (repo / ".omo" / "plans" / "a.md").write_text("plan A", encoding="utf-8")
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "features.md").write_text("feat", encoding="utf-8")

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER}), encoding="utf-8")
    real_denylist = Path(__file__).resolve().parents[2] / "configs" / "external-effect-tools.yaml"

    monkeypatch.setenv("AUTOPHAGY_REPO_ROOT", str(repo))
    monkeypatch.setenv("DRIVE_ARCHIVE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("DRIVE_ARCHIVE_APPROVAL_LOG", str(tmp_path / "state" / "approvals.jsonl"))
    monkeypatch.setenv("DRIVE_ARCHIVE_DENYLIST", str(real_denylist))
    monkeypatch.setenv("INTEROP_CONFIG", str(cfg))
    monkeypatch.setenv("DRIVE_ARCHIVE_DISCORD_STUB", str(tmp_path / "discord"))


def _requested(out: str) -> tuple[str, str]:
    """(action_hash, message_id) of the SYNC-REQUESTED line — fail loudly if absent."""
    match = REQUESTED.search(out)
    assert match is not None, out
    return match.group(1), match.group(3)


def _messages(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "discord").glob("*.json"))


def _records() -> list[Path]:
    return sorted(paths.pending_dir().glob("*.json"))


def test_repeat_request_keeps_the_single_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare(tmp_path, monkeypatch)

    assert sync_cli.main(["request"]) == 0
    hash_a, msg_a = _requested(capsys.readouterr().out)

    assert sync_cli.main(["request"]) == 0  # nothing changed on disk since request #1
    out2 = capsys.readouterr().out

    assert "SYNC-PENDING" in out2
    assert "SYNC-REQUESTED" not in out2
    assert _messages(tmp_path) == [tmp_path / "discord" / f"{msg_a}.json"]

    record = pending.PendingBatchStore(paths.pending_dir()).get(hash_a)
    assert record is not None
    assert record.message_id == msg_a
    assert len(_records()) == 1


def test_changed_batch_supersedes_the_old_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare(tmp_path, monkeypatch)
    discord_dir = tmp_path / "discord"

    assert sync_cli.main(["request"]) == 0
    hash_a, msg_a = _requested(capsys.readouterr().out)

    (tmp_path / "repo" / "docs" / "features.md").write_text("feat v2", encoding="utf-8")

    assert sync_cli.main(["request"]) == 0
    out2 = capsys.readouterr().out
    hash_b, msg_b = _requested(out2)

    assert not (discord_dir / f"{msg_a}.json").exists()
    assert "SYNC-SUPERSEDED reason=batch-changed" in out2
    assert (discord_dir / f"{msg_b}.json").exists()
    assert hash_b != hash_a

    records = _records()
    assert len(records) == 1
    assert json.loads(records[0].read_text(encoding="utf-8"))["action_hash"] == hash_b


def test_claimed_batch_is_never_superseded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare(tmp_path, monkeypatch)
    discord_dir = tmp_path / "discord"

    assert sync_cli.main(["request"]) == 0
    hash_a, msg_a = _requested(capsys.readouterr().out)

    key = approval_adapter.approval_key(sync_cli.project_name())
    with FileKeyLease(paths.approval_lease_dir()).hold(key) as owned:
        assert owned is True  # the confirm watcher owns this batch (up to 900s)

        (tmp_path / "repo" / "docs" / "features.md").write_text("feat v2", encoding="utf-8")

        assert sync_cli.main(["request"]) == 0
        out2 = capsys.readouterr().out

        assert "SYNC-DEFERRED reason=batch-in-flight" in out2
        assert "SYNC-REQUESTED" not in out2
        assert (discord_dir / f"{msg_a}.json").exists()
        assert _messages(tmp_path) == [discord_dir / f"{msg_a}.json"]


def test_missing_message_is_reposted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare(tmp_path, monkeypatch)
    discord_dir = tmp_path / "discord"

    assert sync_cli.main(["request"]) == 0
    hash_a, msg_a = _requested(capsys.readouterr().out)

    (discord_dir / f"{msg_a}.json").unlink()  # owner deleted the approval message

    assert sync_cli.main(["request"]) == 0
    out2 = capsys.readouterr().out
    _, msg_b = _requested(out2)

    assert "SYNC-SUPERSEDED reason=message-missing" in out2
    assert msg_b != msg_a

    record = pending.PendingBatchStore(paths.pending_dir()).get(hash_a)
    assert record is not None
    assert record.message_id == msg_b
    assert len(_records()) == 1


def test_owner_decision_defers_without_destroying_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: a live request on which the owner has already approved.
    _prepare(tmp_path, monkeypatch)
    assert sync_cli.main(["request"]) == 0
    action_hash, message_id = _requested(capsys.readouterr().out)
    reactions = {config.APPROVE_EMOJI: [[OWNER, False]]}
    (tmp_path / "discord" / f"{message_id}.reactions.json").write_text(
        json.dumps(reactions), encoding="utf-8"
    )

    # When: the producer checks the same batch before the watcher consumes it.
    assert sync_cli.main(["request"]) == 0
    output = capsys.readouterr().out

    # Then: the decision surface and pending record remain intact for the watcher.
    assert f"SYNC-DEFERRED reason=owner-decided hash={action_hash}" in output
    assert "SYNC-REQUESTED" not in output
    assert (tmp_path / "discord" / f"{message_id}.json").exists()
    record = pending.PendingBatchStore(paths.pending_dir()).get(action_hash)
    assert record is not None
    assert record.message_id == message_id


def test_corrupt_pending_record_refuses_without_posting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: an unreadable record in the project's pending store.
    _prepare(tmp_path, monkeypatch)
    corrupt = paths.pending_dir() / "corrupt.json"
    corrupt.write_text("{not-json", encoding="utf-8")

    # When: the producer attempts to request approval.
    assert sync_cli.main(["request"]) == 1
    output = capsys.readouterr().out

    # Then: the store fails closed and no Discord request is posted.
    assert "SYNC-REFUSED reason=store-unreadable" in output
    assert "SYNC-REQUESTED" not in output
    assert _messages(tmp_path) == []
    assert corrupt.exists()


def test_same_hash_live_duplicates_collapse_to_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: two live records and messages bound to the same action hash.
    _prepare(tmp_path, monkeypatch)
    assert sync_cli.main(["request"]) == 0
    action_hash, canonical_message = _requested(capsys.readouterr().out)
    stub = StubApprovals(tmp_path / "discord")
    content = stub.content(canonical_message)
    duplicate_message = stub.post(content)
    canonical_path = paths.pending_dir() / f"{action_hash.replace(':', '_')}.json"
    duplicate_payload = json.loads(canonical_path.read_text(encoding="utf-8"))
    duplicate_payload["message_id"] = duplicate_message
    duplicate_payload["created_at"] = "2099-01-01T00:00:00Z"
    (paths.pending_dir() / "duplicate.json").write_text(
        json.dumps(duplicate_payload), encoding="utf-8"
    )

    # When: the producer checks the unchanged batch.
    assert sync_cli.main(["request"]) == 0
    output = capsys.readouterr().out

    # Then: the oldest request is canonical and the duplicate is removed.
    assert f"SYNC-PENDING hash={action_hash}" in output
    assert f"SYNC-SUPERSEDED reason=duplicate-collapsed hash={action_hash}" in output
    assert _messages(tmp_path) == [tmp_path / "discord" / f"{canonical_message}.json"]
    assert len(_records()) == 1


def test_binding_mismatch_refuses_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: a stored record whose live Discord message no longer binds its hash.
    _prepare(tmp_path, monkeypatch)
    assert sync_cli.main(["request"]) == 0
    action_hash, message_id = _requested(capsys.readouterr().out)
    message_path = tmp_path / "discord" / f"{message_id}.json"
    message_path.write_text(
        json.dumps({"id": message_id, "content": "different approval"}), encoding="utf-8"
    )

    # When: the producer checks the unchanged batch.
    assert sync_cli.main(["request"]) == 1
    output = capsys.readouterr().out

    # Then: the mismatched surface is refused without deletion or record loss.
    assert f"SYNC-REFUSED reason=binding-mismatch hash={action_hash} message={message_id}" in output
    assert "SYNC-REQUESTED" not in output
    assert message_path.exists()
    record = pending.PendingBatchStore(paths.pending_dir()).get(action_hash)
    assert record is not None
    assert record.message_id == message_id
