"""Unit specs for drive-archive runtime paths + seed/checkout guard + config (E11 S1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.unit._synthetic import OWNER_ID

from automation.drive_archive import config, paths


def test_state_dir_outside_checkout_is_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = tmp_path / "hermes" / "drive-archive"
    monkeypatch.setenv("AUTOPHAGY_REPO_ROOT", str(repo))
    monkeypatch.setenv("DRIVE_ARCHIVE_STATE_DIR", str(state))

    resolved = paths.state_dir()
    assert resolved.exists()
    assert resolved == state.resolve()


def test_state_dir_shadowing_checkout_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("AUTOPHAGY_REPO_ROOT", str(repo))
    monkeypatch.setenv("DRIVE_ARCHIVE_STATE_DIR", str(repo / "configs" / "state"))

    with pytest.raises(paths.DriveArchivePathError):
        paths.state_dir()


def test_owner_id_reads_interop_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER_ID}), encoding="utf-8")
    monkeypatch.setenv("INTEROP_CONFIG", str(cfg))
    assert config.owner_id() == OWNER_ID


def test_owner_id_missing_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"other": "x"}), encoding="utf-8")
    monkeypatch.setenv("INTEROP_CONFIG", str(cfg))
    with pytest.raises(config.DriveArchiveConfigError):
        config.owner_id()
