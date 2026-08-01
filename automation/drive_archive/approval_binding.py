"""Where one drive-archive batch approval lives — resolved once, then replayed.

A new digest asks the shared directory for its binding exactly once; the pending
batch persists that answer, and every later reaction poll and delete replays the
STORED binding instead of resolving again. A batch written before this schema
carries no binding and drains through the legacy migrator, so a historical digest
stays consumable and is never retargeted.

This is the only drive-archive module allowed to resolve an approval surface: the
transport (``discord``) and the record store (``pending``) consume a binding they
are handed. drive-archive runs from the ops checkout, so ``automation.interop`` is
imported directly rather than through the skills' lazy repo-root seam.
"""

from __future__ import annotations

from typing import Final, Protocol

from automation.drive_archive import config, paths
from automation.drive_archive.pending import PendingBatch
from automation.interop.approval_directory import DiscordChannelDirectory, JsonValue
from automation.interop.approval_surface import (
    ApprovalBinding,
    ApprovalKind,
    ApprovalSurface,
    ApprovalSurfaceError,
    ChannelDirectory,
    legacy_binding,
    resolve_new_binding,
    validate_stored_binding,
)

KIND: Final = ApprovalKind.DRIVE_ARCHIVE


class TokenApi(Protocol):
    """``discord._api``'s call shape — the bot token travels with every call."""

    def __call__(
        self,
        method: str,
        path: str,
        token: str,
        payload: dict[str, JsonValue] | None = None,
    ) -> JsonValue: ...


def approval_directory(token: str, api: TokenApi, owner_id: str) -> ChannelDirectory:
    """The one approval-surface resolver, bound to THIS bot's identity (SI-7)."""

    def call(method: str, path: str, payload: dict[str, JsonValue] | None = None) -> JsonValue:
        return api(method, path, token, payload)

    return DiscordChannelDirectory(
        token=token,
        owner_id=owner_id,
        api=call,
        cache_path=paths.state_dir() / "channel.json",
    )


def new_binding(token: str, api: TokenApi) -> ApprovalBinding:
    """Decide, once, where a brand-new batch digest must be posted."""
    owner = config.owner_id()
    return resolve_new_binding(KIND, approval_directory(token, api, owner), owner)


def stored_binding(record: PendingBatch, directory: ChannelDirectory) -> ApprovalBinding:
    """Replay the binding a record already holds; a pre-schema row drains as legacy."""
    if record.kind and record.kind != KIND.value:
        raise ApprovalSurfaceError(f"pending batch is not a drive-archive approval: {record.kind!r}")
    owner = config.owner_id()
    if not record.is_bound:
        return legacy_binding(KIND, record.channel_id or None, directory, owner)
    binding = ApprovalBinding(
        KIND,
        ApprovalSurface(record.surface),
        record.channel_id,
        record.policy_version,
    )
    return validate_stored_binding(binding, directory, owner)
