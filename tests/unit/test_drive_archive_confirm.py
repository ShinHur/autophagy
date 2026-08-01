"""Confirm/pending/digest specs: owner-only, ⛔-precedence, content-bound (E11 S3/S4)."""

from __future__ import annotations

from pathlib import Path

from automation.drive_archive import digest
from automation.drive_archive.config import APPROVE_EMOJI, CANCEL_EMOJI
from automation.drive_archive.confirm import ReactionDecision, reaction_decision
from automation.drive_archive.discord import StubApprovals
from automation.drive_archive.manifest import BatchManifest, FileEntry
from automation.drive_archive.pending import PendingBatch, PendingBatchStore
from automation.interop.approval_lease import FileKeyLease
from tests.unit._synthetic import OWNER_ID

OWNER = OWNER_ID
TARGET = "tool:drive_archive_batch_upload:drive_archive.batch_upload"


def _pending(action_hash: str = "sha256:" + "a" * 64) -> PendingBatch:
    return PendingBatch(
        action_hash=action_hash,
        target_id=TARGET,
        message_id="msg1",
        project="autophagy",
        created_at="2026-07-24T00:00:00Z",
        files=(FileEntry("docs/features.md", "b" * 64),),
    )


class _FakeTransport:
    def __init__(self, content: str, reactions: dict[str, tuple[tuple[str, bool], ...]]) -> None:
        self._content = content
        self._reactions = reactions

    def content(self, message_id: str) -> str:
        return self._content

    def reaction_users(self, message_id: str, emoji: str) -> tuple[tuple[str, bool], ...]:
        return self._reactions.get(emoji, ())


def test_owner_approve() -> None:
    pending = _pending()
    transport = _FakeTransport(pending.action_hash, {APPROVE_EMOJI: ((OWNER, False),)})
    assert reaction_decision(pending, OWNER, transport) == ReactionDecision.APPROVED


def test_cancel_takes_precedence() -> None:
    pending = _pending()
    transport = _FakeTransport(
        pending.action_hash,
        {APPROVE_EMOJI: ((OWNER, False),), CANCEL_EMOJI: ((OWNER, False),)},
    )
    assert reaction_decision(pending, OWNER, transport) == ReactionDecision.CANCELLED


def test_bot_and_other_reactions_rejected() -> None:
    pending = _pending()
    transport = _FakeTransport(
        pending.action_hash,
        {APPROVE_EMOJI: (("99999", False), (OWNER, True))},  # other user + owner-id-but-bot
    )
    assert reaction_decision(pending, OWNER, transport) == ReactionDecision.PENDING


def test_unbound_message_is_invalid() -> None:
    pending = _pending()
    transport = _FakeTransport("unrelated content", {APPROVE_EMOJI: ((OWNER, False),)})
    assert reaction_decision(pending, OWNER, transport) == ReactionDecision.INVALID


def test_pending_store_roundtrip_and_lease(tmp_path: Path) -> None:
    store = PendingBatchStore(tmp_path / "pending")
    pending = _pending()
    store.put(pending)
    assert store.get(pending.action_hash) == pending
    assert store.all() == (pending,)
    lease = FileKeyLease(tmp_path / "leases")
    with lease.hold("drive:autophagy") as first:
        assert first is True
        with FileKeyLease(tmp_path / "leases").hold("drive:autophagy") as second:
            assert second is False
    with lease.hold("drive:autophagy") as reacquired:
        assert reacquired is True
    store.drop(pending)
    assert store.get(pending.action_hash) is None
    assert store.all() == ()


def test_digest_contains_hash_and_files() -> None:
    files = (FileEntry("docs/features.md", "b" * 64), FileEntry(".omo/plans/a.md", "c" * 64))
    action_hash = "sha256:" + "d" * 64
    text = digest.render(
        digest.DigestRequest(
            BatchManifest(project="autophagy", files=files),
            action_hash,
            "Autophagy 문서아카이브",
            frozenset(),
        )
    )
    assert action_hash in text
    assert "docs/features.md" in text
    assert ".omo/plans/a.md" in text
    assert "autophagy" in text


def test_stub_transport_roundtrip(tmp_path: Path) -> None:
    stub = StubApprovals(tmp_path / "discord")
    message_id = stub.post("hello sha256:abc")
    assert "sha256:abc" in stub.content(message_id)
    assert stub.reaction_users(message_id, APPROVE_EMOJI) == ()
    (tmp_path / "discord" / f"{message_id}.reactions.json").write_text(
        '{"\\u2705": [["' + OWNER + '", false]]}', encoding="utf-8"
    )
    assert stub.reaction_users(message_id, APPROVE_EMOJI) == ((OWNER, False),)
