"""Pure fail-closed decisions for native-memory reconciliation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from .binding import entry_digest, parse_marker, promotion_key
from .model import MemoryEntry
from .state import PromotionRecord

BlockReason = Literal[
    "note_missing",
    "note_not_regular_file",
    "note_hash_mismatch",
    "marker_missing",
    "marker_mismatch",
    "entry_not_found",
    "entry_ambiguous",
]


@dataclass(frozen=True, slots=True)
class ReconcileDecision:
    """Deletion verdict and the exact native entry index it authorizes."""

    verdict: Literal["delete", "skip", "terminal"]
    reason: BlockReason | None
    delete_index: int | None


def decide_reconcile(
    record: PromotionRecord,
    note_bytes: bytes | None,
    note_is_regular_file: bool,
    entries: tuple[MemoryEntry, ...],
) -> ReconcileDecision:
    """Authorize deletion only when every persisted binding still matches."""
    if record.status == "legacy_unbound":
        return ReconcileDecision("skip", None, None)
    if record.status == "reconciled":
        return ReconcileDecision("terminal", None, None)
    if record.status not in ("prepared", "posted"):
        return ReconcileDecision("skip", None, None)

    if note_bytes is None:
        return ReconcileDecision("skip", "note_missing", None)
    if not note_is_regular_file:
        return ReconcileDecision("skip", "note_not_regular_file", None)
    if hashlib.sha256(note_bytes).hexdigest() != record.note_sha256:
        return ReconcileDecision("skip", "note_hash_mismatch", None)

    try:
        note_text = note_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return ReconcileDecision("skip", "marker_missing", None)

    marker = parse_marker(note_text)
    if marker is None:
        return ReconcileDecision("skip", "marker_missing", None)
    if (
        marker.promotion_key
        != promotion_key(record.source_kind, record.entry_sha256)
        or marker.source_kind != record.source_kind
        or marker.entry_digest != record.entry_sha256
        or marker.delete_after_persist is not True
    ):
        return ReconcileDecision("skip", "marker_mismatch", None)

    matching_indices: tuple[int, ...] = tuple(
        index
        for index, entry in enumerate(entries)
        if entry_digest(record.source_kind, entry.text) == record.entry_sha256
    )
    if not matching_indices:
        return ReconcileDecision("terminal", "entry_not_found", None)
    if len(matching_indices) >= 2:
        return ReconcileDecision("skip", "entry_ambiguous", None)
    delete_index = next(iter(matching_indices))
    return ReconcileDecision("delete", None, delete_index)
