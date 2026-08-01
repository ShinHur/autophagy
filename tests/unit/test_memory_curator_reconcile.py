"""Pure reconciliation decisions for owner-approved memory promotion."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Final

import pytest

from automation.memory_curator.binding import (
    MARKER_VERSION,
    DeletionMarker,
    entry_digest,
    promotion_key,
    render_marker,
)
from automation.memory_curator.model import MemoryEntry
from automation.memory_curator.reconcile import ReconcileDecision, decide_reconcile
from automation.memory_curator.state import PromotionRecord, PromotionStatus

_ENTRY_TEXT: Final = "approved exact entry"
_OTHER_TEXT: Final = "different entry"
_ENTRY_DIGEST: Final = entry_digest("memory", _ENTRY_TEXT)
_OTHER_DIGEST: Final = entry_digest("memory", _OTHER_TEXT)


@dataclass(frozen=True, slots=True)
class _Fixture:
    record: PromotionRecord
    note_bytes: bytes
    marker: DeletionMarker
    entries: tuple[MemoryEntry, ...]


def _render_note(marker: DeletionMarker) -> bytes:
    return f"# Promoted memory\n\nBody\n\n{render_marker(marker)}\n".encode()


def _fixture(status: PromotionStatus = "prepared") -> _Fixture:
    marker = DeletionMarker(
        version=MARKER_VERSION,
        promotion_key=promotion_key("memory", _ENTRY_DIGEST),
        source_kind="memory",
        entry_digest=_ENTRY_DIGEST,
        delete_after_persist=True,
    )
    note_bytes = _render_note(marker)
    record = PromotionRecord(
        source_kind="memory",
        entry_sha256=_ENTRY_DIGEST,
        slug="memory-promoted-memory-approved",
        created_at="2026-07-30T00:00:00Z",
        note_sha256=hashlib.sha256(note_bytes).hexdigest(),
        draft_id="draft-1",
        confirm_message_id="message-1",
        status=status,
        posted_at="2026-07-30T00:01:00Z",
        reconciled_at=None,
        backup_path=None,
        last_block_reason=None,
    )
    return _Fixture(
        record=record,
        note_bytes=note_bytes,
        marker=marker,
        entries=(MemoryEntry(_OTHER_TEXT), MemoryEntry(_ENTRY_TEXT)),
    )


def _with_note(fixture: _Fixture, note_bytes: bytes) -> _Fixture:
    return replace(
        fixture,
        note_bytes=note_bytes,
        record=replace(
            fixture.record,
            note_sha256=hashlib.sha256(note_bytes).hexdigest(),
        ),
    )


def _with_marker(fixture: _Fixture, marker: DeletionMarker) -> _Fixture:
    return replace(_with_note(fixture, _render_note(marker)), marker=marker)


@pytest.mark.parametrize("status", ["prepared", "posted"])
def test_delete_when_every_binding_matches(status: PromotionStatus) -> None:
    # Given: an approved note bound to exactly one unchanged native entry.
    fixture = _fixture(status)

    # When: reconciliation is decided.
    decision = decide_reconcile(
        fixture.record,
        fixture.note_bytes,
        True,
        fixture.entries,
    )

    # Then: only that entry index is authorized for deletion.
    assert decision == ReconcileDecision("delete", None, 1)


def test_skip_when_record_is_legacy_unbound() -> None:
    # Given: a legacy record alongside data that would otherwise match.
    fixture = _fixture("legacy_unbound")

    # When: reconciliation is decided.
    decision = decide_reconcile(
        fixture.record,
        fixture.note_bytes,
        True,
        fixture.entries,
    )

    # Then: legacy data remains audit-only.
    assert decision == ReconcileDecision("skip", None, None)


def test_terminal_when_record_is_already_reconciled() -> None:
    # Given: an already reconciled record.
    fixture = _fixture("reconciled")

    # When: reconciliation is decided.
    decision = decide_reconcile(
        fixture.record,
        fixture.note_bytes,
        True,
        fixture.entries,
    )

    # Then: the completed record is terminal.
    assert decision == ReconcileDecision("terminal", None, None)


def test_skip_when_note_is_missing() -> None:
    # Given: a prepared promotion whose note is not present yet.
    fixture = _fixture()

    # When: reconciliation is decided without note bytes.
    decision = decide_reconcile(fixture.record, None, True, fixture.entries)

    # Then: deletion waits for the persisted note.
    assert decision == ReconcileDecision("skip", "note_missing", None)


def test_skip_when_note_is_not_a_regular_file() -> None:
    # Given: matching bytes reached through an untrusted filesystem object.
    fixture = _fixture()

    # When: the caller reports that the note is not a regular file.
    decision = decide_reconcile(
        fixture.record,
        fixture.note_bytes,
        False,
        fixture.entries,
    )

    # Then: the irregular note cannot authorize deletion.
    assert decision == ReconcileDecision("skip", "note_not_regular_file", None)


def test_skip_when_note_hash_differs_from_approval() -> None:
    # Given: note bytes changed after their approved hash was recorded.
    fixture = _fixture()

    # When: reconciliation is decided from the changed bytes.
    decision = decide_reconcile(
        fixture.record,
        fixture.note_bytes + b"changed",
        True,
        fixture.entries,
    )

    # Then: the stale approval cannot authorize deletion.
    assert decision == ReconcileDecision("skip", "note_hash_mismatch", None)


def test_skip_when_note_has_no_marker() -> None:
    # Given: hash-matching note bytes without a deletion marker.
    fixture = _with_note(_fixture(), b"# Promoted memory\n\nNo marker.\n")

    # When: reconciliation is decided.
    decision = decide_reconcile(
        fixture.record,
        fixture.note_bytes,
        True,
        fixture.entries,
    )

    # Then: marker absence fails closed.
    assert decision == ReconcileDecision("skip", "marker_missing", None)


def test_skip_when_hash_matching_note_is_not_utf8() -> None:
    # Given: hash-matching bytes that cannot contain a valid UTF-8 marker.
    fixture = _with_note(_fixture(), b"\xff")

    # When: reconciliation is decided.
    decision = decide_reconcile(
        fixture.record,
        fixture.note_bytes,
        True,
        fixture.entries,
    )

    # Then: decoding failure is treated as a missing marker.
    assert decision == ReconcileDecision("skip", "marker_missing", None)


@pytest.mark.parametrize(
    "marker",
    [
        DeletionMarker(
            MARKER_VERSION,
            promotion_key("user", _ENTRY_DIGEST),
            "user",
            _ENTRY_DIGEST,
            True,
        ),
        DeletionMarker(
            MARKER_VERSION,
            promotion_key("memory", _OTHER_DIGEST),
            "memory",
            _OTHER_DIGEST,
            True,
        ),
        DeletionMarker(
            MARKER_VERSION,
            promotion_key("memory", _ENTRY_DIGEST),
            "memory",
            _ENTRY_DIGEST,
            False,
        ),
    ],
    ids=["different-promotion-key", "different-entry-digest", "deletion-disabled"],
)
def test_skip_when_marker_does_not_authorize_record(marker: DeletionMarker) -> None:
    # Given: a hash-matching note with a coherent marker bound to other authority.
    fixture = _with_marker(_fixture(), marker)

    # When: reconciliation is decided.
    decision = decide_reconcile(
        fixture.record,
        fixture.note_bytes,
        True,
        fixture.entries,
    )

    # Then: any marker mismatch fails closed.
    assert decision == ReconcileDecision("skip", "marker_mismatch", None)


def test_terminal_when_approved_entry_is_no_longer_present() -> None:
    # Given: the approved native entry was edited after promotion.
    fixture = replace(_fixture(), entries=(MemoryEntry("edited entry"),))

    # When: reconciliation is decided.
    decision = decide_reconcile(
        fixture.record,
        fixture.note_bytes,
        True,
        fixture.entries,
    )

    # Then: no deletion occurs and retries terminate.
    assert decision == ReconcileDecision("terminal", "entry_not_found", None)


def test_skip_when_multiple_native_entries_match() -> None:
    # Given: two indistinguishable native entries match the approval.
    fixture = replace(
        _fixture(),
        entries=(MemoryEntry(_ENTRY_TEXT), MemoryEntry(_ENTRY_TEXT)),
    )

    # When: reconciliation is decided.
    decision = decide_reconcile(
        fixture.record,
        fixture.note_bytes,
        True,
        fixture.entries,
    )

    # Then: reconciliation never guesses which duplicate to delete.
    assert decision == ReconcileDecision("skip", "entry_ambiguous", None)
