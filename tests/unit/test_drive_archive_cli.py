"""Offline end-to-end CLI smoke: plan -> request -> (owner ✅) -> upload -> status (E11 S6).

Real subprocess path through a gws shell stub + Discord stub — zero network,
zero real Drive/Discord effect.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.unit._synthetic import OWNER_ID

from automation.drive_archive import approval, paths, pending, sync_cli
from automation.drive_archive.confirm import ReactionDecision, reaction_decision
from automation.drive_archive.discord import StubApprovals

OWNER = OWNER_ID


def _stub_gws(path: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        "  *\"files list\"*) echo '{\"files\":[]}' ;;\n"
        "  *\"files create\"*) echo '{\"id\":\"fold-1\"}' ;;\n"
        "  *\"+upload\"*) echo '{\"id\":\"file-1\"}' ;;\n"
        "  *\"files update\"*) echo '{\"id\":\"file-1\"}' ;;\n"
        "  *\"files get\"*) echo '{\"webViewLink\":\"https://drive.google.com/file/d/file-1/view\"}' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    (repo / ".omo" / "plans").mkdir(parents=True)
    (repo / ".omo" / "plans" / "a.md").write_text("plan A", encoding="utf-8")
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "features.md").write_text("feat", encoding="utf-8")

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"owner_id": OWNER}), encoding="utf-8")
    gws = tmp_path / "gws-stub"
    _stub_gws(gws)
    real_denylist = Path(__file__).resolve().parents[2] / "configs" / "external-effect-tools.yaml"

    monkeypatch.setenv("AUTOPHAGY_REPO_ROOT", str(repo))
    monkeypatch.setenv("DRIVE_ARCHIVE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("DRIVE_ARCHIVE_APPROVAL_LOG", str(tmp_path / "state" / "approvals.jsonl"))
    monkeypatch.setenv("DRIVE_ARCHIVE_DENYLIST", str(real_denylist))
    monkeypatch.setenv("INTEROP_CONFIG", str(cfg))
    monkeypatch.setenv("DRIVE_ARCHIVE_DISCORD_STUB", str(tmp_path / "discord"))
    monkeypatch.setenv("DRIVE_ARCHIVE_GWS_BIN", str(gws))


def test_cli_end_to_end_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _prepare(tmp_path, monkeypatch)

    assert sync_cli.main(["plan"]) == 0
    assert "PLAN files=2" in capsys.readouterr().out

    assert sync_cli.main(["request"]) == 0
    match = re.search(r"SYNC-REQUESTED hash=(\S+) files=2", capsys.readouterr().out)
    assert match is not None
    action_hash = match.group(1)

    record = pending.PendingBatchStore(paths.pending_dir()).get(action_hash)
    assert record is not None
    approval.write_manual_reaction(paths.approval_log(), record, OWNER)  # simulate owner ✅ tick

    assert sync_cli.main(["upload", "--hash", action_hash]) == 0
    assert f"SYNC-UPLOADED hash={action_hash} files=2" in capsys.readouterr().out

    assert sync_cli.main(["request"]) == 0
    assert "NO-CHANGES" in capsys.readouterr().out  # cursor advanced -> re-run is a no-op

    assert sync_cli.main(["status"]) == 0
    assert "STATUS pending=0" in capsys.readouterr().out


def test_cli_upload_unknown_hash_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _prepare(tmp_path, monkeypatch)
    assert sync_cli.main(["upload", "--hash", "sha256:deadbeef"]) == 1
    assert "UPLOAD-REFUSED" in capsys.readouterr().out


def test_request_digest_aggregates_and_stays_reaction_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _prepare(tmp_path, monkeypatch)
    qa_dir = tmp_path / "repo" / "docs" / "qa" / "E11"
    qa_dir.mkdir(parents=True)
    for index in range(15):
        (qa_dir / f"{index:02d}-note.md").write_text(f"note {index}", encoding="utf-8")
    monkeypatch.setenv("DRIVE_ARCHIVE_ROOT_NAME", "테스트 아카이브")

    assert sync_cli.main(["request"]) == 0
    out = capsys.readouterr().out
    match = re.search(r"SYNC-REQUESTED hash=(\S+) files=17", out)
    assert match is not None
    action_hash = match.group(1)

    record = pending.PendingBatchStore(paths.pending_dir()).get(action_hash)
    assert record is not None

    stub = StubApprovals(tmp_path / "discord")
    content = stub.content(record.message_id)
    assert "분류별 집계" in content
    assert "- `qa/` 15건" in content
    assert "- `plans/` 1건" in content
    assert "- `features/` 1건" in content
    assert "신규 17 · 변경 0" in content
    assert "테스트 아카이브" in content
    assert "docs/qa/E11/00-note.md" not in content
    assert len(content) <= 2000

    assert reaction_decision(record, OWNER, stub) == ReactionDecision.PENDING
    (tmp_path / "discord" / f"{record.message_id}.reactions.json").write_text(
        '{"\\u2705": [["' + OWNER + '", false]]}', encoding="utf-8"
    )
    assert reaction_decision(record, OWNER, stub) == ReactionDecision.APPROVED


def test_deduped_request_stays_approvable_and_uploads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare(tmp_path, monkeypatch)

    assert sync_cli.main(["request"]) == 0
    out1 = capsys.readouterr().out
    match = re.search(r"SYNC-REQUESTED hash=(\S+) files=(\d+) message=(\S+)", out1)
    assert match is not None
    action_hash = match.group(1)
    msg_a = match.group(3)

    assert sync_cli.main(["request"]) == 0
    out2 = capsys.readouterr().out
    assert "SYNC-PENDING" in out2
    assert "SYNC-REQUESTED" not in out2

    record = pending.PendingBatchStore(paths.pending_dir()).get(action_hash)
    assert record is not None
    assert record.message_id == msg_a

    (tmp_path / "discord" / f"{msg_a}.reactions.json").write_text(
        '{"\\u2705": [["' + OWNER + '", false]]}', encoding="utf-8"
    )
    stub = StubApprovals(tmp_path / "discord")
    assert reaction_decision(record, OWNER, stub) == ReactionDecision.APPROVED
    approval.write_manual_reaction(paths.approval_log(), record, OWNER)

    assert sync_cli.main(["upload", "--hash", action_hash]) == 0
    out3 = capsys.readouterr().out
    assert f"SYNC-UPLOADED hash={action_hash} files=2" in out3

    assert sync_cli.main(["request"]) == 0
    out4 = capsys.readouterr().out
    assert "NO-CHANGES" in out4


def test_archive_root_defaults_to_document_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DRIVE_ARCHIVE_ROOT_NAME", raising=False)

    assert sync_cli.root_folder_name() == "Autophagy 문서아카이브"
