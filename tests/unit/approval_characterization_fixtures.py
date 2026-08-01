"""Production-shaped fixtures for the approval-surface characterization locks
(AS-0.2, split out under AS-1.11).

Helper module, not a test module: the name carries no ``test_`` prefix so pytest
does not collect it.

Importing this module puts the repo root and ``skills/mail/scripts`` on
``sys.path``. Every characterization test module therefore imports it BEFORE it
imports ``triage_*`` — that import order is load-bearing, not cosmetic.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

from approval_conformance_inventory import _REPO
from tests.unit._synthetic import (
    APPROVALS_CHANNEL_ID,
    OWNER_DM_CHANNEL_ID,
    OWNER_ID,
    fake_snowflake,
)

sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "skills" / "mail" / "scripts"))
sys.modules.setdefault("mail_wrapper", ModuleType("mail_wrapper"))

import triage_binding  # noqa: E402
import triage_confirm  # noqa: E402
import triage_gate  # noqa: E402
from automation.interop.approval_surface import ChannelFacts  # noqa: E402

# Production surfaces, used as fixtures: the owner, this bot's DM with them, the
# guild #approvals channel, and a SECOND approvals channel an older message may
# still live in — the precedence case the migration exists to serve.
BOUND_APPROVALS_CHANNEL_ID: Final = fake_snowflake(4)
EXPECTED_CANONICAL_HASHES: Final = ("05b9b3759dd6830ec0d8fdaf0fb5a93f76168dba689ec14a65eafdeff6633c7e", "05b9b3759dd6830ec0d8fdaf0fb5a93f76168dba689ec14a65eafdeff6633c7e")
# Machine-independent stand-ins for the interpreter and bridge path that
# production argv carries; see ``_pin_send_argv_prefix``.
_PINNED_INTERPRETER: Final = "python3"
_PINNED_BRIDGE: Final = "/opt/autophagy/skills/mail/scripts/site_mail_backend.py"
_BINDING_FIELDS: Final = ("kind", "surface", "channel_id", "policy_version")


class _FakeDirectory:
    """Hand-written ``ChannelDirectory`` that counts every question a gate asks."""

    def __init__(self) -> None:
        self.approvals_calls = 0
        self.dm_calls = 0
        self.described: list[str] = []

    def owner_dm(self) -> str:
        self.dm_calls += 1
        return OWNER_DM_CHANNEL_ID

    def skill_approvals(self) -> str:
        self.approvals_calls += 1
        return APPROVALS_CHANNEL_ID

    def describe(self, channel_id: str) -> ChannelFacts:
        self.described.append(channel_id)
        if channel_id == OWNER_DM_CHANNEL_ID:
            return ChannelFacts(1, "", (OWNER_ID,))
        return ChannelFacts(0, "approvals", ())


def _bind_mail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _FakeDirectory:
    """Confine the mail gate to tmp_path and to a fake directory — never Discord."""
    monkeypatch.setenv("TRIAGE_GATE_DIR", str(tmp_path / "mail-gate"))
    monkeypatch.setenv("TRIAGE_MAIL_HOME", str(tmp_path / "mail-home"))
    monkeypatch.setenv("TRIAGE_MAILON_PYTHON", "python3")
    directory = _FakeDirectory()
    monkeypatch.setattr(triage_binding, "approval_directory", lambda: directory)
    monkeypatch.setattr(triage_gate.site_mail_backend, "config_sha256", lambda: "sha256:" + "f" * 64)
    monkeypatch.setattr(triage_gate.site_mail_backend, "verify_config_sha256", lambda _expected: None)
    monkeypatch.setattr(triage_confirm, "owner_id", lambda: OWNER_ID)
    _pin_send_argv_prefix(monkeypatch)
    return directory


def _pin_send_argv_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the interpreter and bridge path that ``build_send_argv`` embeds in argv.

    A draft's content hash binds the exact argv that will send it, and production
    argv opens with ``sys.executable`` and the resolved bridge path. Both are
    machine-specific, so a frozen expected digest would encode whichever checkout
    generated it and would fail on every other machine. Pinning only those two
    path elements keeps the lock meaningful: the canonical request payload — the
    part that actually binds recipient, subject and body — is still hashed
    verbatim.
    """
    backend = triage_gate.site_mail_backend
    build_send_argv = backend.build_send_argv

    def _stable_argv(request: object, expected_config_sha256: str) -> tuple[str, ...]:
        argv = build_send_argv(request, expected_config_sha256)
        return (_PINNED_INTERPRETER, _PINNED_BRIDGE, *argv[2:])

    monkeypatch.setattr(backend, "build_send_argv", _stable_argv)


def _mail_draft(kind: str) -> dict:
    return triage_gate.create_draft(
        uid="uid-1", sender="발신자 <s@example.invalid>", mail_subject="문의",
        to="owner@example.invalid", subject="Re: 문의", body="본문", sensitive=False,
        tags=(), category="important", flags=("reply_needed",), kind=kind,
    )
