"""Deterministic calendar↔coordination arbitration (post-incident 2026-07-20).

The classifier decides which single skill owns one meeting request so that a
peer-named request with an exact time can never dual-fire (solo calendar draft
AND a peer negotiation that drifts to a different slot).
"""

from __future__ import annotations

import sys
from datetime import datetime
from importlib import import_module
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "skills" / "calendar" / "scripts"))

calendar_core = import_module("calendar_core")
calendar_routing = import_module("calendar_routing")

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=calendar_core.KST)  # Wednesday
PEER = "agent-peer"


@pytest.fixture(autouse=True)
def _peers_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CALENDAR_PEERS_CONFIG", str(_REPO / "configs" / "peers.yaml"))


# --- exact-time signal --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["내일 오후 3시 실험 미팅", "모레 14:30 치과", "다음주 화요일 오전 10시 반 세미나"],
)
def test_resolves_to_exact_time_true_for_concrete_slots(text: str) -> None:
    assert calendar_routing.resolves_to_exact_time(text, NOW) is True


@pytest.mark.parametrize(
    "text",
    ["다음주쯤 미팅", "내일 미팅", "다음주 오전에 미팅", f"{PEER}랑 다음주 수요일 오전에 30분 미팅"],
)
def test_resolves_to_exact_time_false_for_windows_and_vague(text: str) -> None:
    assert calendar_routing.resolves_to_exact_time(text, NOW) is False


# --- no peer involved ---------------------------------------------------------


def test_no_peer_exact_time_is_calendar() -> None:
    assert calendar_routing.classify_meeting_request("내일 오후 3시 실험 미팅", NOW) == "calendar"


def test_no_peer_vague_is_clarify() -> None:
    assert calendar_routing.classify_meeting_request("내일 미팅 잡아줘", NOW) == "clarify"


# --- the incident: peer named + exact time → calendar (NOT coordination) -------


def test_peer_named_exact_time_no_cue_is_calendar() -> None:
    # A peer name with a fixed morning slot means the owner fixed their own slot;
    # title token. Must NOT trigger a negotiation that drifts to another day.
    result = calendar_routing.classify_meeting_request(
        f"{PEER}랑 다음주 수요일 오전 10시 30분 미팅", NOW
    )
    assert result == "calendar"


def test_peer_named_exact_time_via_summary_only_is_calendar() -> None:
    # Peer name only in the LLM-produced title, exact time in the text.
    result = calendar_routing.classify_meeting_request(
        f"다음주 수요일 오전 10시 {PEER} 미팅", NOW
    )
    assert result == "calendar"


# --- peer named + coordination intent → coordination --------------------------


def test_peer_named_window_with_cue_is_coordination() -> None:
    result = calendar_routing.classify_meeting_request(
        f"{PEER}와 다음주 오전에 가능한 시간 조율해줘", NOW
    )
    assert result == "coordination"


def test_explicit_peer_flag_window_is_coordination() -> None:
    result = calendar_routing.classify_meeting_request(
        "다음주 오전에 미팅", NOW, peer_flag=PEER
    )
    assert result == "coordination"


# --- conflicting / insufficient signals → clarify (fail-closed) ---------------


def test_peer_named_exact_time_with_cue_is_clarify() -> None:
    # "10시에 가능한지 물어봐" — fixed slot AND negotiate cue conflict; the
    # negotiator cannot honour an exact slot, so fail-closed to clarify.
    result = calendar_routing.classify_meeting_request(
        f"{PEER}에게 다음주 수요일 오전 10시 가능한지 물어봐", NOW
    )
    assert result == "clarify"


def test_bare_peer_name_without_cue_or_flag_is_clarify() -> None:
    # A bare peer name in vague free text is not enough to start a negotiation.
    result = calendar_routing.classify_meeting_request(f"{PEER} 다음주 미팅", NOW)
    assert result == "clarify"


def test_explicit_exact_slot_flag_treats_peer_name_as_title() -> None:
    # An already-resolved single ISO slot passed by the caller is exact; with no
    # negotiate cue the peer name is a title token, so this is a solo calendar
    # event (never a negotiation that could drift off the fixed slot).
    result = calendar_routing.classify_meeting_request(
        f"{PEER} 미팅", NOW, peer_flag=PEER, explicit_exact_slot=True
    )
    assert result == "calendar"
