"""Immutable typed records stored by the memory curator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from .model import MemoryKind

PromotionStatus = Literal["prepared", "posted", "reconciled", "legacy_unbound"]
PendingOwnerPhase = Literal["posted", "deleted"]


class StateError(ValueError):
    """Raised when persisted curator state cannot be parsed without guessing."""


@dataclass(frozen=True, slots=True)
class PromotionRecord:
    source_kind: MemoryKind
    entry_sha256: str
    slug: str
    created_at: str
    note_sha256: str
    draft_id: str | None
    confirm_message_id: str | None
    status: PromotionStatus
    posted_at: str | None
    reconciled_at: str | None
    backup_path: str | None
    last_block_reason: str | None


@dataclass(frozen=True, slots=True)
class PendingOwnerEvent:
    key: str
    phase: PendingOwnerPhase
    preview: str
    twin_kind: str | None
    draft_id: str | None
    freed_chars: int | None


@dataclass(frozen=True, slots=True)
class AlertState:
    last_observed_signature: str | None
    last_sent_signature: str | None
    last_sent_at: str | None
    pending_signature: str | None


@dataclass(frozen=True, slots=True)
class CuratorState:
    version: int
    promotions: Mapping[str, PromotionRecord]
    alert: AlertState
    pending_owner_events: Mapping[str, PendingOwnerEvent]

    def __post_init__(self) -> None:
        object.__setattr__(self, "promotions", MappingProxyType(dict(self.promotions)))
        object.__setattr__(
            self,
            "pending_owner_events",
            MappingProxyType(dict(self.pending_owner_events)),
        )
