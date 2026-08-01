"""Drive-archive adapter for the shared owner-approval lifecycle."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final

from automation.drive_archive import approval_binding, config, digest, discord
from automation.drive_archive.confirm import owner_reacted
from automation.drive_archive.manifest import BatchManifest
from automation.drive_archive.pending import PendingBatch, PendingBatchStore
from automation.interop.approval_lifecycle import (
    ApprovalIntent,
    ApprovalRecordsError,
    ApprovalRequest,
    ApprovalSurfaceError,
    PostedApproval,
    Probe,
)
from automation.interop.approval_surface import POLICY_VERSION, required_surface

_TRANSPORT_ERRORS: Final = (
    discord.DiscordError,
    OSError,
    json.JSONDecodeError,
    KeyError,
    TypeError,
)


def approval_key(project: str) -> str:
    return f"drive:{project}"


@dataclass(frozen=True, slots=True)
class DriveApprovalPayload:
    batch: BatchManifest
    target_id: str
    root_name: str
    tracked: frozenset[str]


@dataclass(frozen=True, slots=True)
class DriveApprovalGate:
    store: PendingBatchStore
    transport: discord.DiscordApprovals | discord.StubApprovals
    owner_id: str
    channel_id: str
    payload: DriveApprovalPayload

    def outstanding(self, key: str) -> tuple[ApprovalRequest, ...]:
        prefix = "drive:"
        if not key.startswith(prefix):
            raise ApprovalRecordsError(key)
        project = key.removeprefix(prefix)
        return tuple(
            ApprovalRequest(
                key=key,
                action_hash=record.action_hash,
                message_id=record.message_id,
                channel_id=self.channel_id,
                created_at=record.created_at,
            )
            for record in self.store.all_strict()
            if record.project == project
        )

    def probe(self, request: ApprovalRequest) -> Probe:
        try:
            content = self.transport.content(request.message_id)
            if not content:
                return Probe.MISSING
            if request.action_hash not in content:
                return Probe.BINDING_MISMATCH
            cancelled = self.transport.reaction_users(request.message_id, config.CANCEL_EMOJI)
            approved = self.transport.reaction_users(request.message_id, config.APPROVE_EMOJI)
        except _TRANSPORT_ERRORS as error:
            raise ApprovalSurfaceError(str(error)) from error
        if owner_reacted(cancelled, self.owner_id):
            return Probe.CANCELLED
        if owner_reacted(approved, self.owner_id):
            return Probe.APPROVED
        return Probe.BOUND_PENDING

    def delete(self, request: ApprovalRequest) -> None:
        try:
            self.transport.delete(request.message_id)
        except _TRANSPORT_ERRORS as error:
            raise ApprovalSurfaceError(str(error)) from error

    def drop(self, request: ApprovalRequest) -> None:
        project = request.key.removeprefix("drive:")
        expected = (request.action_hash, request.message_id, project)
        for record in self.store.all_strict():
            actual = (record.action_hash, record.message_id, record.project)
            if actual == expected:
                self.store.drop(record)
                return

    def post(self, intent: ApprovalIntent) -> PostedApproval:
        text = digest.render(
            digest.DigestRequest(
                manifest=self.payload.batch,
                action_hash=intent.action_hash,
                root_name=self.payload.root_name,
                tracked=self.payload.tracked,
            )
        )
        try:
            message_id = self.transport.post(text)
            self.transport.add_reaction(message_id, config.APPROVE_EMOJI)
            self.transport.add_reaction(message_id, config.CANCEL_EMOJI)
        except _TRANSPORT_ERRORS as error:
            raise ApprovalSurfaceError(str(error)) from error
        return PostedApproval(message_id=message_id, channel_id=intent.channel_id)

    def commit(self, intent: ApprovalIntent, posted: PostedApproval, created_at: str) -> None:
        self.store.put(
            PendingBatch(
                action_hash=intent.action_hash,
                target_id=self.payload.target_id,
                message_id=posted.message_id,
                project=self.payload.batch.project,
                created_at=created_at,
                files=self.payload.batch.files,
                kind=approval_binding.KIND.value,
                surface=required_surface(approval_binding.KIND).value,
                channel_id=posted.channel_id,
                policy_version=POLICY_VERSION,
            )
        )
