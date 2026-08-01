"""Contract for the curator's best-effort near-cap alert DM.

The alert is a notification, not an approval, so it lives in effects and
fails closed: a dry-run prints, a real send creates the owner DM channel
once then posts, a missing token no-ops, and any transport error is
swallowed so a bad cron tick never crashes.  The Discord POST is injected
so this is host-testable without touching Discord.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from automation.memory_curator import effects
from automation.memory_curator.binding import PromotionReceipt
from automation.memory_curator.effects import (
    _twin_meta_and_body,
    _wiki_gate_promote,
    alert_owner,
    post_promotion,
)
from automation.memory_curator.promotion import PromotionProposal, build_proposal
from skills.wiki.scripts import wiki_store


def test_dry_run_prints_and_does_not_post(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("MEMORY_CURATOR_DRY_RUN", "1")
    calls: list[tuple[str, str, dict[str, str]]] = []

    def post(token: str, path: str, payload: dict[str, str]) -> dict[str, object]:
        calls.append((token, path, payload))
        return {"id": "x"}

    sent = alert_owner("near cap!", post=post)
    assert calls == []
    assert sent is False
    assert "DRY-RUN alert: near cap!" in capsys.readouterr().out


def test_creates_owner_dm_channel_then_posts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    _ = config.write_text('{"owner_id": "999"}', encoding="utf-8")
    monkeypatch.setattr("automation.memory_curator.effects._INTEROP_CONFIG", config)
    monkeypatch.delenv("MEMORY_CURATOR_DRY_RUN", raising=False)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")
    calls: list[tuple[str, str, dict[str, str]]] = []

    def post(token: str, path: str, payload: dict[str, str]) -> dict[str, object]:
        calls.append((token, path, payload))
        return {"id": "chan123"}

    sent = alert_owner("\u26a0\ufe0f near cap", post=post)
    assert calls[0] == ("tok", "/users/@me/channels", {"recipient_id": "999"})
    assert calls[1] == ("tok", "/channels/chan123/messages", {"content": "\u26a0\ufe0f near cap"})
    assert sent is True


def test_no_token_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEMORY_CURATOR_DRY_RUN", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    calls: list[tuple[str, str, dict[str, str]]] = []

    def post(token: str, path: str, payload: dict[str, str]) -> dict[str, object]:
        calls.append((token, path, payload))
        return {"id": "y"}

    sent = alert_owner("x", post=post)
    assert calls == []
    assert sent is False


def test_transport_error_is_swallowed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    _ = config.write_text('{"owner_id": "999"}', encoding="utf-8")
    monkeypatch.setattr("automation.memory_curator.effects._INTEROP_CONFIG", config)
    monkeypatch.delenv("MEMORY_CURATOR_DRY_RUN", raising=False)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "tok")

    def boom(
        _token: str, _path: str, _payload: dict[str, str]
    ) -> dict[str, object]:
        raise RuntimeError("discord down")

    assert alert_owner("x", post=boom) is False



# --- promotion effect ------------------------------------------------------- #
def test_twin_meta_is_observed_advisory_capped() -> None:
    proposal = build_proposal("앞으로 배려를 원칙으로 한다", source_kind="user")
    meta, body = _twin_meta_and_body(proposal, "2026-01-01T00:00:00Z")
    assert meta["kind"] == "principle"
    assert meta["authority"] == "advisory"  # SI-3 proposer cap
    assert meta["provenance"] == "observed"  # SI-3 proposer cap
    assert meta["tags"] == ["twin", "principle"]
    assert body == proposal.body


def test_post_promotion_returns_runner_result() -> None:
    proposal = build_proposal("원칙으로 한다", source_kind="memory")
    receipt = PromotionReceipt("draft-abc", "message-123", proposal.slug, "note-hash")

    assert post_promotion(proposal, runner=lambda _p: receipt) == receipt
    assert post_promotion(proposal, runner=lambda _p: None) is None


def test_post_promotion_swallows_runner_error() -> None:
    proposal = build_proposal("원칙으로 한다", source_kind="memory")

    def boom(_proposal: PromotionProposal) -> PromotionReceipt | None:
        raise RuntimeError("wiki gate down")

    assert post_promotion(proposal, runner=boom) is None


def test_wiki_gate_promote_returns_confirmation_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MEMORY_CURATOR_DRY_RUN", raising=False)
    proposal = build_proposal("원칙으로 한다", source_kind="memory")
    note_texts: list[str] = []
    fake_gate = ModuleType("wiki_gate")

    def create_draft(action: str, slug: str, note_text: str, surface: str) -> dict[str, str]:
        note_texts.append(note_text)
        assert (action, slug, surface) == ("create", proposal.slug, "dm")
        return {"id": "draft-abc", "sha256": "note-hash"}

    def post_confirm_message(_draft: dict[str, str]) -> dict[str, str]:
        return {"confirm_message_id": "message-123"}

    fake_gate.__dict__["create_draft"] = create_draft
    fake_gate.__dict__["post_confirm_message"] = post_confirm_message
    monkeypatch.setitem(sys.modules, "wiki_gate", fake_gate)
    monkeypatch.setitem(sys.modules, "wiki_store", wiki_store)

    receipt = _wiki_gate_promote(proposal)

    assert receipt == PromotionReceipt("draft-abc", "message-123", proposal.slug, "note-hash")
    _meta, body = wiki_store.parse_note(note_texts[0])
    assert body.rstrip("\n") == proposal.body


def test_wiki_gate_promote_dry_run_does_not_create_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEMORY_CURATOR_DRY_RUN", "1")
    fake_gate = ModuleType("wiki_gate")

    def forbidden_create_draft(*_args: str) -> dict[str, str]:
        pytest.fail("dry-run must not create a wiki draft")

    fake_gate.__dict__["create_draft"] = forbidden_create_draft
    monkeypatch.setitem(sys.modules, "wiki_gate", fake_gate)
    proposal = build_proposal("원칙으로 한다", source_kind="memory")

    assert _wiki_gate_promote(proposal) is None


def test_read_twin_returns_regular_file_bytes(tmp_path: Path) -> None:
    note = tmp_path / "principle.md"
    _ = note.write_bytes(b"wiki-note\n")

    assert effects.read_twin("principle", wiki_root=tmp_path) == b"wiki-note\n"


def test_read_twin_returns_none_when_file_is_missing(tmp_path: Path) -> None:
    assert effects.read_twin("missing", wiki_root=tmp_path) is None


def test_read_twin_never_follows_symlink(tmp_path: Path) -> None:
    note = tmp_path / "principle.md"
    _ = note.write_bytes(b"wiki-note\n")
    (tmp_path / "linked.md").symlink_to(note)

    assert effects.read_twin("linked", wiki_root=tmp_path) is None
