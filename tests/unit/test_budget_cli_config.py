from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "skills" / "budget" / "scripts"))

import budget_cli  # noqa: E402


def test_query_exits_config_error_without_sheet_id_or_subprocess(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given: a live-sheet query with neither a fixture nor its required identifier
    monkeypatch.delenv("BUDGET_SHEET_FILE", raising=False)
    monkeypatch.delenv("BUDGET_SHEET_ID", raising=False)
    monkeypatch.setattr(sys, "argv", ["budget", "query"])

    def no_subprocess(*_args: str, **_kwargs: str) -> None:
        raise AssertionError("missing sheet ID must fail before subprocess execution")

    monkeypatch.setattr(budget_cli.subprocess, "run", no_subprocess)

    # When: the CLI reads the live budget sheet configuration
    exit_code = budget_cli.main()

    # Then: it refuses with the missing-variable error before invoking gws
    assert exit_code == 3
    assert "BUDGET_SHEET_ID" in capsys.readouterr().err
