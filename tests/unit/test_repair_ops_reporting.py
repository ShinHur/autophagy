from __future__ import annotations

import pytest
import pwd

from automation.repair import repair_ops_reporting


def test_ticket_board_when_agent_account_is_absent_then_completion_remains_best_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an isolated repair E2E host has no Unix agent account for the Kanban mirror.
    def missing_agent(_name: str) -> None:
        raise KeyError("agent")

    monkeypatch.setattr(pwd, "getpwnam", missing_agent)

    # When: the completed repair lifecycle asks its best-effort ticket board to mirror completion.
    repair_ops_reporting.HermesTicketBoard().complete("t-repair-1", "repair applied")

    # Then: the repository repair remains complete even though its optional mirror is unavailable.
