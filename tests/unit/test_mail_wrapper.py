from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "skills" / "mail" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import mail_gmail_send  # noqa: E402
import site_mail_backend  # noqa: E402
import triage_core  # noqa: E402


_FAKE_BACKEND = """\
import json
import os
import pathlib
import sys

request = json.loads(sys.stdin.read())
log_path = os.environ.get("FAKE_SITE_BACKEND_LOG", "")
if log_path:
    pathlib.Path(log_path).write_text(json.dumps(request, sort_keys=True))
operation = request["operation"]
if operation == "list":
    response = {
        "operation": "list", "status": "ok", "synced": request["sync"],
        "mails": [{
            "message_id": "message-1", "folder": "inbox",
            "subject": "Synthetic subject", "sender": "sender@example.invalid",
            "received_at": "2030-01-02T03:04:05Z",
        }],
    }
elif operation == "get":
    response = {
        "operation": "get", "status": "ok",
        "mail": {
            "message_id": request["message_id"], "folder": "inbox",
            "subject": "Synthetic subject", "sender": "sender@example.invalid",
            "received_at": "2030-01-02T03:04:05Z", "body": "Synthetic body",
        },
    }
elif operation == "status":
    response = {
        "operation": "status", "status": "ok", "available": True,
        "account": "site", "message": "ready",
    }
elif operation == "resolve":
    response = {
        "operation": "resolve", "status": "ok", "query": request["query"],
        "candidates": [{
            "kind": "directory", "name": "Example Person",
            "email": "person@example.invalid", "organization": "Example Organization",
        }],
    }
elif operation == "send":
    response = {
        "operation": "send", "status": "submitted", "message_id": "sent-1",
        "verified": True, "attachment_count": len(request["attachments"]),
        "attachment_manifest_sha256": request["attachment_manifest_sha256"],
    }
else:
    response = {
        "operation": operation, "status": "error", "error_code": "unsupported",
        "message": "unsupported operation", "retryable": False, "stage": "validation",
    }
print(json.dumps(response, separators=(",", ":"), sort_keys=True))
"""


@pytest.fixture()
def backend_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    backend = tmp_path / "fake_site_backend.py"
    backend.write_text(_FAKE_BACKEND, encoding="utf-8")
    config = tmp_path / "site-backend.json"
    config.write_text(
        json.dumps(
            {
                "contract_version": 1,
                "backend_id": "mail.example.invalid",
                "organization": "Example Organization",
                "command": [sys.executable, str(backend)],
                "timeout_seconds": 30,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SITE_MAIL_BACKEND_CONFIG", str(config))
    return config


def _send_request() -> site_mail_backend.SendRequest:
    return site_mail_backend.SendRequest(
        to="recipient@example.invalid",
        subject="Synthetic subject",
        body="Synthetic body",
        attachments=(),
        attachment_manifest_sha256=None,
    )


def _run_wrapper(*arguments: str) -> tuple[int, site_mail_backend.JsonObject]:
    process = subprocess.run(
        [sys.executable, str(_SCRIPTS / "mail_wrapper.py"), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    return process.returncode, json.loads(process.stdout)


def test_all_five_operations_use_the_json_contract(backend_config: Path) -> None:
    listed = site_mail_backend.list(site_mail_backend.ListRequest(limit=5, sync=True))
    fetched = site_mail_backend.get(
        site_mail_backend.GetRequest(message_id="message-1", include_body=True)
    )
    health = site_mail_backend.status(site_mail_backend.StatusRequest())
    resolved = site_mail_backend.resolve(site_mail_backend.ResolveRequest(query="Example Person"))
    sent = site_mail_backend.send(
        _send_request(), expected_config_sha256=site_mail_backend.config_sha256()
    )

    assert listed.mails[0].message_id == fetched.mail.message_id == "message-1"
    assert listed.synced is True
    assert fetched.mail.body == "Synthetic body"
    assert health.available is True and health.account == "site"
    assert resolved.candidates[0].email == "person@example.invalid"
    assert sent.status == "submitted" and sent.verified is True


@pytest.mark.parametrize(
    "config_text",
    [
        "{not-json",
        json.dumps({"contract_version": 1}),
        json.dumps(
            {
                "contract_version": 1,
                "backend_id": "{{SITE_ID}}",
                "organization": "Example Organization",
                "command": ["/tmp/backend"],
                "timeout_seconds": 30,
            }
        ),
    ],
)
def test_invalid_config_fails_closed(
    config_text: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "invalid.json"
    config.write_text(config_text, encoding="utf-8")
    monkeypatch.setenv("SITE_MAIL_BACKEND_CONFIG", str(config))

    with pytest.raises(site_mail_backend.BackendUnavailable):
        site_mail_backend.status(site_mail_backend.StatusRequest())


def test_missing_config_env_and_file_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SITE_MAIL_BACKEND_CONFIG", raising=False)
    with pytest.raises(site_mail_backend.BackendUnavailable):
        site_mail_backend.config_sha256()

    monkeypatch.setenv("SITE_MAIL_BACKEND_CONFIG", str(tmp_path / "missing.json"))
    with pytest.raises(site_mail_backend.BackendUnavailable):
        site_mail_backend.config_sha256()


def test_config_hash_is_canonical_and_bound_into_the_action(
    backend_config: Path,
) -> None:
    first_hash = site_mail_backend.config_sha256()
    payload = json.loads(backend_config.read_text(encoding="utf-8"))
    backend_config.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    second_hash = site_mail_backend.config_sha256()
    first_argv = site_mail_backend.build_send_argv(_send_request(), first_hash)

    payload["organization"] = "Example Organization Two"
    backend_config.write_text(json.dumps(payload), encoding="utf-8")
    changed_hash = site_mail_backend.config_sha256()
    changed_argv = site_mail_backend.build_send_argv(_send_request(), changed_hash)

    assert first_hash == second_hash
    assert first_hash in first_argv
    assert changed_hash != first_hash
    assert triage_core.external_effect_action_hash(first_argv) != (
        triage_core.external_effect_action_hash(changed_argv)
    )


def test_send_reverifies_config_hash_immediately_before_execution(
    backend_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved_hash = site_mail_backend.config_sha256()
    payload = json.loads(backend_config.read_text(encoding="utf-8"))
    payload["backend_id"] = "replacement.example.invalid"
    backend_config.write_text(json.dumps(payload), encoding="utf-8")
    execution_log = tmp_path / "execution.json"
    monkeypatch.setenv("FAKE_SITE_BACKEND_LOG", str(execution_log))

    with pytest.raises(site_mail_backend.BackendUnavailable, match="hash"):
        site_mail_backend.send(_send_request(), expected_config_sha256=approved_hash)

    assert execution_log.exists() is False


def test_wrapper_maps_generic_list_get_status_and_resolve(backend_config: Path) -> None:
    list_rc, listed = _run_wrapper("list", "--limit", "3", "--sync")
    get_rc, fetched = _run_wrapper("get", "message-1", "--body")
    status_rc, health = _run_wrapper("status")
    resolve_rc, resolved = _run_wrapper("resolve", "--name", "Example Person")

    assert (list_rc, get_rc, status_rc, resolve_rc) == (0, 0, 0, 0)
    assert listed["mails"][0]["uid"] == fetched["mail"]["uid"] == "message-1"
    assert health["available"] is True
    assert resolved["candidates"][0]["email"] == "person@example.invalid"


def test_gmail_build_does_not_load_site_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SITE_MAIL_BACKEND_CONFIG", raising=False)
    action = mail_gmail_send.build_action(
        mail_gmail_send.NewMailRequest(
            options=mail_gmail_send.DeliveryOptions(account="gmail"),
            to="recipient@example.invalid",
            subject="Synthetic subject",
            body="Synthetic body",
        )
    )

    assert action.account == "gmail"
    assert action.argv[:3] == ("gws", "gmail", "+send")
