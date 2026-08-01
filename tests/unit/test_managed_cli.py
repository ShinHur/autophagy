from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from automation.managed_sync import cli
from automation.managed_sync.pipeline import (
    FailedRelease,
    RemovalRequest,
    SkillOptions,
    SkippedSkill,
    StagedRelease,
    SyncConfig,
    SyncReport,
)
from automation.managed_sync.state import (
    ManagedSyncState,
    record_activated,
    record_verified,
    save_state,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEED_PATH = _REPO_ROOT / "configs" / "managed-sync.default.json"
_CRON_PATH = _REPO_ROOT / "automation" / "managed_sync" / "cron" / "managed_sync_watch.py"

_REQUIRED_KEYS = frozenset(
    {
        "remote_url",
        "publisher",
        "allowed_signers",
        "mirror_dir",
        "ssh_key_path",
        "quarantine_dir",
        "state_path",
        "skills",
    }
)


def _digest(letter: str) -> str:
    return letter * 64


def _config_payload(tmp_path: Path) -> dict[str, Any]:
    return {
        "remote_url": "ssh://feed.example/managed-skills.git",
        "publisher": "publisher",
        "allowed_signers": str(tmp_path / "allowed_signers"),
        "mirror_dir": str(tmp_path / "mirror"),
        "ssh_key_path": str(tmp_path / "feed_key"),
        "quarantine_dir": str(tmp_path / "quarantine"),
        "state_path": str(tmp_path / "state.json"),
        "skills": {"managed-demo": {"opt_in": True, "pin": None}},
    }


def _install_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> Path:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("MANAGED_SYNC_CONFIG", str(config_path))
    return config_path


def _stage_release(quarantine_dir: Path, skill: str, sequence: int, digest: str) -> Path:
    release = quarantine_dir / skill / digest
    (release / skill).mkdir(parents=True)
    provenance = {
        "publisher": "publisher",
        "sequence": sequence,
        "tag": f"{skill}/v{sequence}",
        "verified_at": "2026-07-24T00:00:00+00:00",
    }
    (release / "provenance.json").write_text(
        json.dumps(provenance, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    return release


def test_config_seed_when_parsed_then_has_all_required_keys_with_placeholders() -> None:
    payload = json.loads(_SEED_PATH.read_text(encoding="utf-8"))

    assert frozenset(payload) == _REQUIRED_KEYS
    assert payload["remote_url"].startswith("ssh://")
    assert "REPLACE_ME" in payload["remote_url"]
    for key in ("mirror_dir", "quarantine_dir", "state_path"):
        assert payload[key].startswith("~/.hermes/managed-sync/")
    skills = payload["skills"]
    assert isinstance(skills, dict) and skills
    for options in skills.values():
        assert frozenset(options) == frozenset({"opt_in", "pin"})
        assert isinstance(options["opt_in"], bool)
        assert options["pin"] is None


def test_sync_when_config_file_is_missing_then_exit_2_names_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "config.json"
    monkeypatch.setenv("MANAGED_SYNC_CONFIG", str(missing))

    assert cli.main(["sync"]) == 2

    error_output = capsys.readouterr().err
    assert "CONFIG-ERROR" in error_output
    assert str(missing) in error_output


def test_sync_when_required_key_is_missing_then_exit_2_names_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _config_payload(tmp_path)
    del payload["remote_url"]
    _install_config(tmp_path, monkeypatch, payload)

    assert cli.main(["sync"]) == 2

    assert "missing required key: remote_url" in capsys.readouterr().err


def test_sync_when_config_is_not_json_then_exit_2_names_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("not-json{{{", encoding="utf-8")
    monkeypatch.setenv("MANAGED_SYNC_CONFIG", str(config_path))

    assert cli.main(["sync"]) == 2

    error_output = capsys.readouterr().err
    assert "not valid JSON" in error_output
    assert str(config_path) in error_output


def test_sync_when_skill_options_are_malformed_then_exit_2_names_the_skill_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _config_payload(tmp_path)
    payload["skills"]["managed-demo"] = {"opt_in": True}
    _install_config(tmp_path, monkeypatch, payload)

    assert cli.main(["sync"]) == 2

    assert "skills.managed-demo" in capsys.readouterr().err


def test_sync_when_pipeline_reports_then_prints_deterministic_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_config(tmp_path, monkeypatch, _config_payload(tmp_path))
    report = SyncReport(
        staged=(StagedRelease("managed-demo", 2, _digest("b")),),
        skipped=(SkippedSkill("managed-idle", "not-opted-in"),),
        failed=(FailedRelease("managed-bad", "managed-bad/v1", "BAD-SIGNATURE"),),
        removal_requests=(
            RemovalRequest("managed-demo", _digest("c"), "activated digest is revoked"),
        ),
        rolled_back=(StagedRelease("managed-demo", 1, _digest("d")),),
    )
    seen: dict[str, SyncConfig] = {}

    def fake_sync_all(
        config: SyncConfig, state: ManagedSyncState, *, allow_rollback: int | None = None
    ) -> SyncReport:
        del state, allow_rollback
        seen["config"] = config
        return report

    monkeypatch.setattr(cli, "sync_all", fake_sync_all)

    assert cli.main(["sync"]) == 0

    assert capsys.readouterr().out == (
        f"SYNC-STAGED skill=managed-demo sequence=2 digest={_digest('b')}\n"
        f"SYNC-ROLLBACK-STAGED skill=managed-demo sequence=1 digest={_digest('d')}\n"
        "SYNC-SKIPPED skill=managed-idle reason=not-opted-in\n"
        "SYNC-FAILED skill=managed-bad tag=managed-bad/v1 reason=BAD-SIGNATURE\n"
        f"SYNC-REMOVAL-REQUEST skill=managed-demo digest={_digest('c')}"
        " reason=activated digest is revoked\n"
        "SYNC-SUMMARY staged=1 skipped=1 failed=1 removal_requests=1 rolled_back=1\n"
    )
    config = seen["config"]
    assert config.remote_url == "ssh://feed.example/managed-skills.git"
    assert config.state_path == tmp_path / "state.json"
    assert config.skills["managed-demo"] == SkillOptions(opt_in=True, pin=None)


def test_sync_when_report_is_empty_then_prints_zero_summary_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_config(tmp_path, monkeypatch, _config_payload(tmp_path))
    monkeypatch.setattr(
        cli, "sync_all", lambda config, state, *, allow_rollback=None: SyncReport((), (), ())
    )

    assert cli.main(["sync"]) == 0

    assert capsys.readouterr().out == (
        "SYNC-SUMMARY staged=0 skipped=0 failed=0 removal_requests=0 rolled_back=0\n"
    )


def test_sync_when_allow_rollback_given_then_accepted_with_deterministic_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_config(tmp_path, monkeypatch, _config_payload(tmp_path))
    seen: dict[str, int | None] = {}

    def fake_sync_all(
        config: SyncConfig, state: ManagedSyncState, *, allow_rollback: int | None = None
    ) -> SyncReport:
        del config, state
        seen["allow_rollback"] = allow_rollback
        return SyncReport((), (), ())

    monkeypatch.setattr(cli, "sync_all", fake_sync_all)

    assert cli.main(["sync", "--allow-rollback", "3"]) == 0

    output = capsys.readouterr().out
    assert output.startswith("SYNC-ROLLBACK-NOTE sequence=3 ")
    assert seen["allow_rollback"] == 3


def test_allow_rollback_when_given_to_other_subcommands_then_argparse_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_config(tmp_path, monkeypatch, _config_payload(tmp_path))
    for argv in (
        ["status", "--allow-rollback", "3"],
        ["activate-instructions", "managed-demo", "--allow-rollback", "3"],
    ):
        with pytest.raises(SystemExit) as excinfo:
            _ = cli.main(argv)
        assert excinfo.value.code == 2
    _ = capsys.readouterr()


def test_status_when_state_and_quarantine_exist_then_renders_per_skill_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _config_payload(tmp_path)
    payload["skills"]["managed-idle"] = {"opt_in": False, "pin": None}
    _install_config(tmp_path, monkeypatch, payload)
    state = record_verified(ManagedSyncState(), "managed-demo", 2, _digest("b"))
    state = record_activated(state, "managed-demo", _digest("a"))
    save_state(tmp_path / "state.json", state)
    quarantine_skill_dir = tmp_path / "quarantine" / "managed-demo"
    (quarantine_skill_dir / _digest("a")).mkdir(parents=True)
    (quarantine_skill_dir / _digest("b")).mkdir()

    assert cli.main(["status"]) == 0

    assert capsys.readouterr().out == (
        "STATUS skill=managed-demo opt_in=true highest_sequence=2"
        f" activated_digest={_digest('a')} pending=1\n"
        "STATUS skill=managed-idle opt_in=false highest_sequence=0"
        " activated_digest=- pending=0\n"
    )


def test_activate_instructions_when_two_digests_quarantined_then_names_newest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_config(tmp_path, monkeypatch, _config_payload(tmp_path))
    quarantine_dir = tmp_path / "quarantine"
    _ = _stage_release(quarantine_dir, "managed-demo", 1, _digest("a"))
    newest = _stage_release(quarantine_dir, "managed-demo", 2, _digest("b"))
    live_root = tmp_path / "live"
    live_root.mkdir()

    assert cli.main(["activate-instructions", "managed-demo", "--live-root", str(live_root)]) == 0

    assert capsys.readouterr().out == (
        f"automation/deploy-skill.sh managed-demo --activate-managed {newest}\n"
    )


def test_activate_instructions_when_live_base_exists_then_refuses_with_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_config(tmp_path, monkeypatch, _config_payload(tmp_path))
    _ = _stage_release(tmp_path / "quarantine", "managed-demo", 1, _digest("a"))
    live_root = tmp_path / "live"
    (live_root / "demo").mkdir(parents=True)

    assert cli.main(["activate-instructions", "managed-demo", "--live-root", str(live_root)]) == 1

    error_output = capsys.readouterr().err
    assert "COLLISION-BLOCK" in error_output
    assert "live base demo" in error_output


def test_activate_instructions_when_nothing_quarantined_then_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_config(tmp_path, monkeypatch, _config_payload(tmp_path))
    live_root = tmp_path / "live"
    live_root.mkdir()

    assert cli.main(["activate-instructions", "managed-demo", "--live-root", str(live_root)]) == 1

    assert "no quarantined release" in capsys.readouterr().err


def test_activate_instructions_when_name_lacks_managed_prefix_then_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_config(tmp_path, monkeypatch, _config_payload(tmp_path))

    assert cli.main(["activate-instructions", "demo"]) == 2

    assert "must start with managed-" in capsys.readouterr().err


def test_cron_wrapper_when_scanned_then_syncs_only_and_never_touches_discord() -> None:
    source = _CRON_PATH.read_text(encoding="utf-8")

    assert "deploy-skill.sh" not in source
    assert "activate" not in source
    assert "--allow-rollback" not in source
    assert "discord.com" not in source
    assert "discord" not in source.lower()


def test_cron_wrapper_when_scanned_then_has_no_agent_cron_markers() -> None:
    source = _CRON_PATH.read_text(encoding="utf-8")

    assert "fcntl.flock" in source
    assert ".env.secrets" in source
    assert "env=" in source
    assert "AUTOPHAGY_REPO_ROOT" in source
    assert '"sync"' in source
