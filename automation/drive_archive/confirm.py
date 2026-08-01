"""Owner-only, content-bound reaction resolution with cancellation precedence.

Mirrors ``repair_ops_reaction_watch.reaction_decision`` / ``budget_confirm``:
only the owner's non-bot reaction counts, ⛔ wins over ✅, and the message must
still reference this batch's action_hash or the verdict is INVALID (fail closed).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from automation.drive_archive.config import APPROVE_EMOJI, CANCEL_EMOJI
from automation.drive_archive.pending import PendingBatch


class ApprovalPollTransport(Protocol):
    """Read only the posted content and the two terminal reaction lists."""

    def content(self, message_id: str) -> str: ...

    def reaction_users(self, message_id: str, emoji: str) -> tuple[tuple[str, bool], ...]: ...


class ReactionDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    CANCELLED = "cancelled"
    INVALID = "invalid"


def owner_reacted(users: tuple[tuple[str, bool], ...], owner_id: str) -> bool:
    return any(user_id == owner_id and not bot for user_id, bot in users)


def reaction_decision(
    pending: PendingBatch, owner_id: str, transport: ApprovalPollTransport
) -> ReactionDecision:
    if pending.action_hash not in transport.content(pending.message_id):
        return ReactionDecision.INVALID
    if owner_reacted(transport.reaction_users(pending.message_id, CANCEL_EMOJI), owner_id):
        return ReactionDecision.CANCELLED
    if owner_reacted(transport.reaction_users(pending.message_id, APPROVE_EMOJI), owner_id):
        return ReactionDecision.APPROVED
    return ReactionDecision.PENDING
