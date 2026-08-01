"""Offline contracts for the first-class Gmail send/reply action builder (RTS-2 C2)."""
from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "skills" / "mail" / "scripts"))

import mail_gmail_send  # noqa: E402
import triage_core  # noqa: E402
from mail_account_routing import AccountSelectionError  # noqa: E402


def test_build_gmail_new_mail_uses_canonical_argv_without_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a Gmail new-mail request and a subprocess sentinel that must stay silent
    subprocess_calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def unexpected_subprocess(argv: list[str], **kwargs: str) -> subprocess.CompletedProcess[str]:
        subprocess_calls.append((tuple(argv), dict(kwargs.get("env", {}))))
        raise AssertionError("building a Gmail action must not invoke gws")

    monkeypatch.setattr(mail_gmail_send.subprocess, "run", unexpected_subprocess)
    request = mail_gmail_send.NewMailRequest(
        options=mail_gmail_send.DeliveryOptions(
            account="gmail",
            cc="reviewer@example.com",
            bcc="archive@example.com",
            from_address="alias@example.com",
        ),
        to="recipient@example.com",
        subject="Project update",
        body="Status is green.",
    )

    # When: the canonical action is built
    action = mail_gmail_send.build_action(request)

    # Then: it has the exact gws argv but caused zero subprocess invocations
    assert action.argv == (
        "gws",
        "gmail",
        "+send",
        "--to",
        "recipient@example.com",
        "--subject",
        "Project update",
        "--body",
        "Status is green.",
        "--cc",
        "reviewer@example.com",
        "--bcc",
        "archive@example.com",
        "--from",
        "alias@example.com",
    )
    assert action.account == "gmail"
    assert action.attachment_manifest == ()
    assert action.attachment_manifest_sha256 is None
    assert subprocess_calls == []


def test_build_gmail_reply_uses_threading_argv() -> None:
    # Given: a reply whose source thread belongs to Gmail
    request = mail_gmail_send.ReplyMailRequest(
        options=mail_gmail_send.DeliveryOptions(account="gmail"),
        reply_to_account="gmail",
        reply_message_id="18f1a2b3c4d",
        body="Thanks, received.",
    )

    # When: the canonical action is built
    action = mail_gmail_send.build_action(request)

    # Then: gws +reply owns the thread and needs no manual threading headers
    assert action.argv == (
        "gws",
        "gmail",
        "+reply",
        "--message-id",
        "18f1a2b3c4d",
        "--body",
        "Thanks, received.",
    )
    assert action.account == "gmail"


def test_multi_attachment_manifest_is_bound_and_gws_runs_only_after_callback(
    tmp_path: Path,
) -> None:
    # Given: two local attachments and a recording fake gws executable
    first = tmp_path / "notes.txt"
    second = tmp_path / "table.csv"
    first.write_text("first attachment\n", encoding="utf-8")
    second.write_text("second attachment\n", encoding="utf-8")
    request = mail_gmail_send.NewMailRequest(
        options=mail_gmail_send.DeliveryOptions(
            account="gmail", attachments=(first, second)
        ),
        to="recipient@example.com",
        subject="Files",
        body="Please review the attachments.",
    )
    action = mail_gmail_send.build_action(request)
    subprocess_calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def fake_gws(
        argv: list[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: int,
        check: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        assert capture_output is True
        assert text is True
        assert timeout == 900
        assert check is False
        subprocess_calls.append((tuple(argv), env))
        return subprocess.CompletedProcess(argv, 0, stdout="submitted", stderr="")

    # When: the approval callback first refuses execution
    def deny_execution(_action: mail_gmail_send.CanonicalMailAction) -> None:
        raise RuntimeError("approval required")

    with pytest.raises(RuntimeError, match="approval required"):
        mail_gmail_send.execute_approved(
            action,
            approved_execution=deny_execution,
            runner=fake_gws,
            environment={"PATH": "/fake/bin"},
        )

    # Then: the callback stopped gws; a later explicit approval executes the frozen argv once
    assert subprocess_calls == []
    approvals: list[mail_gmail_send.CanonicalMailAction] = []
    result = mail_gmail_send.execute_approved(
        action,
        approved_execution=approvals.append,
        runner=fake_gws,
        environment={"PATH": "/fake/bin"},
    )
    assert result == mail_gmail_send.ExecutionResult(0, "submitted", "")
    assert approvals == [action]
    assert subprocess_calls == [
        (
            (
                "gws",
                "gmail",
                "+send",
                "--to",
                "recipient@example.com",
                "--subject",
                "Files",
                "--body",
                "Please review the attachments.",
                "-a",
                str(first.resolve()),
                "-a",
                str(second.resolve()),
            ),
            {"PATH": "/fake/bin"},
        )
    ]
    assert action.attachment_manifest == (
        mail_gmail_send.AttachmentManifestEntry(
            source_path_private=str(first.resolve()),
            filename="notes.txt",
            size_bytes=len(b"first attachment\n"),
            mime_type="text/plain",
            sha256=hashlib.sha256(b"first attachment\n").hexdigest(),
        ),
        mail_gmail_send.AttachmentManifestEntry(
            source_path_private=str(second.resolve()),
            filename="table.csv",
            size_bytes=len(b"second attachment\n"),
            mime_type="text/csv",
            sha256=hashlib.sha256(b"second attachment\n").hexdigest(),
        ),
    )
    assert triage_core.attachment_manifest_sha256(action.manifest_for_verification()) == (
        action.attachment_manifest_sha256
    )


def test_site_action_uses_the_stable_bridge_and_binds_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "site-backend.json"
    config.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "backend_id": "mail.example.invalid",
                "organization": "Example Organization",
                "command": ["/opt/example-site-backend/bin/backend"],
                "timeout_seconds": 30,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SITE_MAIL_BACKEND_CONFIG", str(config))
    request = mail_gmail_send.NewMailRequest(
        options=mail_gmail_send.DeliveryOptions(account="site"),
        to="recipient@example.com",
        subject="Site path",
        body="Synthetic body.",
    )
    action = mail_gmail_send.build_action(request)

    assert action.account == "site"
    assert action.argv[1].endswith("site_mail_backend.py")
    assert action.argv[2] == "send"
    expected_hash = action.argv[action.argv.index("--expected-config-sha256") + 1]
    request_json = json.loads(action.argv[action.argv.index("--request-json") + 1])
    assert expected_hash.startswith("sha256:")
    assert request_json["operation"] == "send"
    assert request_json["to"] == "recipient@example.com"


def test_delivery_account_has_no_default() -> None:
    parameter = inspect.signature(mail_gmail_send.DeliveryOptions).parameters["account"]
    assert parameter.default is inspect.Parameter.empty


def test_invalid_account_is_rejected_by_the_shared_account_contract() -> None:
    # Given: an unsupported explicit account
    request = mail_gmail_send.NewMailRequest(
        options=mail_gmail_send.DeliveryOptions(account="other"),
        to="recipient@example.com",
        subject="Subject",
        body="Body",
    )

    # When / Then: the single routing contract rejects it before an action exists
    with pytest.raises(AccountSelectionError):
        mail_gmail_send.build_action(request)


def test_reply_without_message_id_is_rejected() -> None:
    # Given: a Gmail reply missing its target message id
    request = mail_gmail_send.ReplyMailRequest(
        options=mail_gmail_send.DeliveryOptions(account="gmail"),
        reply_to_account="gmail",
        reply_message_id=" ",
        body="Body",
    )

    # When / Then: no unthreaded reply action is constructed
    with pytest.raises(mail_gmail_send.MissingReplyMessageIdError):
        mail_gmail_send.build_action(request)


def test_missing_attachment_is_rejected_with_existing_typed_policy_error(tmp_path: Path) -> None:
    # Given: an attachment path that does not exist
    request = mail_gmail_send.NewMailRequest(
        options=mail_gmail_send.DeliveryOptions(
            account="gmail", attachments=(tmp_path / "missing.txt",)
        ),
        to="recipient@example.com",
        subject="Subject",
        body="Body",
    )

    # When / Then: attachment validation refuses before gws is eligible to run
    with pytest.raises(triage_core.AttachmentPolicyError, match="첨부파일을 읽을 수 없습니다"):
        mail_gmail_send.build_action(request)
