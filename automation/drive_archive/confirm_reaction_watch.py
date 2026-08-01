"""Fail-closed owner-reaction watcher for pending drive-archive batch approvals.

Reactions-only (규약 (a)): each tick reads only the digest content + its two
terminal reaction lists — never messages. On a bound owner ✅ it writes the
manual_reaction approval record, then runs the gated upload in a child process
that receives the Discord credential via an explicit ``env=`` (규약 (b-2)).
⛔ / expiry discard the batch. Uncertain reactions are retained for a later tick.
A child that times out — and any other per-batch failure — is isolated: the
record is kept (never removed, never auto-approved), the upload resumes from the
cursor on the next tick, and the remaining batches of the tick still run.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, assert_never

from automation.drive_archive import approval, approval_adapter, config
from automation.drive_archive.discord import DiscordApprovals, DiscordError
from automation.drive_archive.confirm import ReactionDecision, reaction_decision
from automation.drive_archive.pending import PendingBatch, PendingBatchStore
from automation.interop.approval_lease import ApprovalLease, FileKeyLease
from automation.interop.approval_lifecycle import (
    ApprovalRequest,
    Probe,
    resolve_owner_decision,
)

APPROVAL_TTL = timedelta(hours=24)
UPLOAD_TIMEOUT_SECONDS = 900


class ApprovalTransport(Protocol):
    """The reaction-poll surface plus the two discard-time notifications."""

    def content(self, message_id: str) -> str: ...

    def reaction_users(self, message_id: str, emoji: str) -> tuple[tuple[str, bool], ...]: ...

    def delete(self, message_id: str) -> None: ...

    def dm(self, owner: str, content: str) -> str: ...


class UploadCommand(Protocol):
    """Run the gated upload only after a watcher verdict (child re-verifies the gate)."""

    def run(self, pending: PendingBatch) -> bool: ...


@dataclass(frozen=True, slots=True)
class CliUploadCommand:
    """Invoke the drive-archive upload CLI with the credential only in the child env."""

    cli: Path
    token: str
    repo_root: Path

    def run(self, pending: PendingBatch) -> bool:
        env = dict(os.environ)
        env["DISCORD_BOT_TOKEN"] = self.token
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            str(self.repo_root) if not existing else str(self.repo_root) + os.pathsep + existing
        )
        try:
            result = subprocess.run(
                (sys.executable, str(self.cli), "upload", "--hash", pending.action_hash),
                capture_output=True,
                check=False,
                cwd=str(self.repo_root),
                env=env,
                text=True,
                timeout=UPLOAD_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            # The batch is resumable: the child persisted every file it finished,
            # so the pending record stays and the next tick continues the remainder.
            note = f"UPLOAD-TIMEOUT hash={pending.action_hash} sec={UPLOAD_TIMEOUT_SECONDS}"
            print(f"{note} — 다음 틱에서 이어서 진행", file=sys.stderr)
            return False
        return result.returncode == 0


class UploadIncompleteError(RuntimeError):
    action_hash: str

    def __init__(self, action_hash: str) -> None:
        self.action_hash = action_hash
        super().__init__(f"upload incomplete: {action_hash}")


def _parse_created(created_at: str) -> datetime:
    return datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class DriveArchiveWatcher:
    store: PendingBatchStore
    transport: ApprovalTransport
    commands: UploadCommand
    owner_id: str
    approval_log: Path
    now: Callable[[], datetime]
    lease: ApprovalLease

    def run_once(self) -> None:
        for pending in self.store.all():
            try:
                self._process(pending)
            # BLE001 stays unsuppressed: isolate only expected boundary failures.
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
                # Fail-closed: nothing here removes a record or writes an approval —
                # the batch simply stays pending and is retried on the next tick.
                print(
                    f"BATCH-FAILED hash={pending.action_hash} detail={error}",
                    file=sys.stderr,
                )

    def _process(self, pending: PendingBatch) -> None:
        request = ApprovalRequest(
            key=approval_adapter.approval_key(pending.project),
            action_hash=pending.action_hash,
            message_id=pending.message_id,
            channel_id=pending.channel_id,
            created_at=pending.created_at,
        )
        transport = self._bound(pending)
        if self.now().astimezone(UTC) - _parse_created(pending.created_at) >= APPROVAL_TTL:
            with self.lease.hold(request.key) as owned:
                if owned:
                    self._discard(pending, transport, "approval_expired")
            return
        try:
            _ = resolve_owner_decision(
                request, PendingDecision(self, pending, transport), self.lease
            )
        except UploadIncompleteError:
            return

    def _bound(self, pending: PendingBatch) -> ApprovalTransport:
        """Poll the channel the RECORD names: a stored binding is authoritative (SI-1)."""
        if pending.channel_id and isinstance(self.transport, DiscordApprovals):
            return replace(self.transport, channel_id=pending.channel_id)
        return self.transport

    def _approve(self, pending: PendingBatch) -> None:
        approval.write_manual_reaction(self.approval_log, pending, self.owner_id, now=self.now())
        if not self.commands.run(pending):
            raise UploadIncompleteError(pending.action_hash)

    def _discard(self, pending: PendingBatch, transport: ApprovalTransport, reason: str) -> None:
        self.store.drop(pending)
        self._notify(pending, transport, reason)

    def _notify(self, pending: PendingBatch, transport: ApprovalTransport, reason: str) -> None:
        try:
            transport.delete(pending.message_id)
            _ = transport.dm(
                self.owner_id, f"⛔ Drive 아카이브 배치 {reason} — hash {pending.action_hash}"
            )
        except (OSError, DiscordError):
            return  # discard already committed; notification is best-effort


@dataclass(frozen=True, slots=True)
class PendingDecision:
    watcher: DriveArchiveWatcher
    pending: PendingBatch
    transport: ApprovalTransport

    def probe(self, request: ApprovalRequest) -> Probe:
        _ = request
        match reaction_decision(self.pending, self.watcher.owner_id, self.transport):
            case ReactionDecision.APPROVED:
                return Probe.APPROVED
            case ReactionDecision.CANCELLED:
                return Probe.CANCELLED
            case ReactionDecision.PENDING:
                return Probe.BOUND_PENDING
            case ReactionDecision.INVALID:
                return Probe.BINDING_MISMATCH
            case unreachable:
                assert_never(unreachable)

    def apply(self, request: ApprovalRequest, decision: Probe) -> None:
        _ = request
        match decision:
            case Probe.APPROVED:
                self.watcher._approve(self.pending)
            case Probe.CANCELLED:
                self.watcher._discard(self.pending, self.transport, "owner_cancelled")
            case (
                Probe.BOUND_PENDING
                | Probe.MISSING
                | Probe.BINDING_MISMATCH
                | Probe.UNVERIFIABLE
            ) as invalid:
                raise AssertionError(f"invalid terminal decision: {invalid.value}")
            case unreachable:
                assert_never(unreachable)

    def drop(self, request: ApprovalRequest) -> None:
        _ = request
        self.watcher.store.drop(self.pending)


def main() -> int:
    from automation.drive_archive import discord, paths

    transport = discord.configured_approvals()
    token = getattr(transport, "token", os.environ.get("DISCORD_BOT_TOKEN", ""))
    cli = paths.repo_root() / "automation" / "drive_archive" / "sync_cli.py"
    watcher = DriveArchiveWatcher(
        store=PendingBatchStore(paths.pending_dir()),
        transport=transport,
        commands=CliUploadCommand(cli=cli, token=token, repo_root=paths.repo_root()),
        owner_id=config.owner_id(),
        approval_log=paths.approval_log(),
        now=lambda: datetime.now(UTC),
        lease=FileKeyLease(paths.approval_lease_dir()),
    )
    watcher.run_once()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
