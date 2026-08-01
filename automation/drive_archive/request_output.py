"""Legacy stdout formatting for verdicts and their CLEARED requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import assert_never

from automation.drive_archive.approval_adapter import DriveApprovalGate
from automation.interop.approval_lifecycle import (
    ApprovalIntent,
    ApprovalRecordsError,
    Outcome,
    Reason,
    Verdict,
)


@dataclass(frozen=True, slots=True)
class RequestReport:
    verdict: Verdict
    intent: ApprovalIntent
    gate: DriveApprovalGate
    file_count: int


def _identity(report: RequestReport) -> tuple[str, str]:
    requests = report.verdict.blocked
    if not requests:
        try:
            requests = report.gate.outstanding(report.intent.key)
        except ApprovalRecordsError:
            return (report.intent.action_hash, "unknown")
    if not requests:
        return (report.intent.action_hash, "unknown")
    request = min(requests, key=lambda item: (item.created_at, item.message_id))
    return (request.action_hash, request.message_id)


def _print_cleared(report: RequestReport) -> None:
    for cleared in report.verdict.cleared:
        match cleared.reason:
            case Reason.CONTENT_CHANGED:
                token = "batch-changed"
            case Reason.MESSAGE_MISSING:
                token = "message-missing"
            case Reason.DUPLICATE_COLLAPSED:
                token = "duplicate-collapsed"
            case (
                Reason.LEASE_HELD
                | Reason.OWNER_DECIDED
                | Reason.UNVERIFIABLE
                | Reason.BINDING_MISMATCH
                | Reason.STORE_UNREADABLE
                | Reason.SUPERSEDE_FAILED
                | Reason.POSTING_JOURNAL_STALE
            ) as invalid:
                raise AssertionError(f"invalid cleared reason: {invalid.value}")
            case unreachable:
                assert_never(unreachable)
        request = cleared.request
        print(
            f"SYNC-SUPERSEDED reason={token} hash={request.action_hash}"
            f" message={request.message_id}"
        )


def print_report(report: RequestReport) -> int:
    _print_cleared(report)
    match report.verdict.outcome:
        case Outcome.POSTED:
            posted = report.verdict.posted
            if posted is None:
                raise AssertionError("posted verdict missing message")
            print(
                f"SYNC-REQUESTED hash={report.intent.action_hash} files={report.file_count}"
                f" message={posted.message_id}"
            )
            return 0
        case Outcome.PENDING:
            live = report.verdict.live
            if live is None:
                raise AssertionError("pending verdict missing request")
            print(
                f"SYNC-PENDING hash={live.action_hash} files={report.file_count}"
                f" message={live.message_id}"
            )
            return 0
        case Outcome.DEFERRED:
            action_hash, _ = _identity(report)
            match report.verdict.reason:
                case Reason.LEASE_HELD:
                    token = "batch-in-flight"
                case Reason.OWNER_DECIDED:
                    token = "owner-decided"
                case Reason.UNVERIFIABLE:
                    token = "unverifiable"
                case (
                    Reason.BINDING_MISMATCH
                    | Reason.STORE_UNREADABLE
                    | Reason.SUPERSEDE_FAILED
                    | Reason.POSTING_JOURNAL_STALE
                    | Reason.CONTENT_CHANGED
                    | Reason.MESSAGE_MISSING
                    | Reason.DUPLICATE_COLLAPSED
                ) as invalid:
                    raise AssertionError(f"invalid deferred reason: {invalid.value}")
                case None:
                    raise AssertionError("deferred verdict missing reason")
                case unreachable:
                    assert_never(unreachable)
            print(f"SYNC-DEFERRED reason={token} hash={action_hash}")
            return 0
        case Outcome.REFUSED:
            action_hash, message_id = _identity(report)
            match report.verdict.reason:
                case (
                    Reason.BINDING_MISMATCH
                    | Reason.STORE_UNREADABLE
                    | Reason.SUPERSEDE_FAILED
                    | Reason.POSTING_JOURNAL_STALE
                ) as reason:
                    print(
                        f"SYNC-REFUSED reason={reason.value} hash={action_hash}"
                        f" message={message_id}"
                    )
                case (
                    Reason.LEASE_HELD
                    | Reason.OWNER_DECIDED
                    | Reason.UNVERIFIABLE
                    | Reason.CONTENT_CHANGED
                    | Reason.MESSAGE_MISSING
                    | Reason.DUPLICATE_COLLAPSED
                ) as invalid:
                    raise AssertionError(f"invalid refused reason: {invalid.value}")
                case None:
                    raise AssertionError("refused verdict missing reason")
                case unreachable:
                    assert_never(unreachable)
            return 1
        case unreachable:
            assert_never(unreachable)
