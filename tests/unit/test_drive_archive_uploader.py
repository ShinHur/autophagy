"""Uploader specs: gate re-verify fail-closed, receipts, cursor advance, hash binding (E11 S5)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from automation.drive_archive import approval, gate_binding, manifest, uploader
from automation.drive_archive.drive_client import DriveArchiveError, DriveClient
from automation.drive_archive.pending import PendingBatch
from automation.interop.external_effect_gate import ApprovalContext
from tests.unit._synthetic import OWNER_ID

OWNER = OWNER_ID


def _parse_q(query: str) -> tuple[str, str, bool]:
    name = re.search(r"name = '((?:[^'\\]|\\.)*)'", query).group(1)
    parent = re.search(r"'([^']+)' in parents", query).group(1)
    return name, parent, "application/vnd.google-apps.folder" in query


class FakeGws:
    def __init__(self) -> None:
        self.folders: dict[tuple[str, str], str] = {}
        self.files: dict[tuple[str, str], str] = {}
        self.calls: list[list[str]] = []
        self._n = 0

    def _new(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def __call__(self, argv: list[str]) -> dict[str, object]:
        self.calls.append(argv)
        op = argv[2]
        if op == "+upload":
            parent = argv[argv.index("--parent") + 1]
            name = argv[argv.index("--name") + 1]
            file_id = self._new("file")
            self.files[(name, parent)] = file_id
            return {"id": file_id}
        method = argv[3]
        if method == "list":
            params = json.loads(argv[argv.index("--params") + 1])
            name, parent, is_folder = _parse_q(params["q"])
            registry = self.folders if is_folder else self.files
            found = registry.get((name, parent))
            return {"files": [{"id": found, "name": name}] if found else []}
        if method == "create":
            meta = json.loads(argv[argv.index("--json") + 1])
            folder_id = self._new("fold")
            self.folders[(meta["name"], meta["parents"][0])] = folder_id
            return {"id": folder_id}
        if method == "update":
            return {"id": json.loads(argv[argv.index("--params") + 1])["fileId"]}
        if method == "get":
            fid = json.loads(argv[argv.index("--params") + 1])["fileId"]
            return {"webViewLink": f"https://drive.google.com/file/d/{fid}/view"}
        raise AssertionError(argv)


def _seed_repo(root: Path) -> list[str]:
    (root / ".omo" / "plans").mkdir(parents=True)
    (root / ".omo" / "plans" / "a.md").write_text("plan A", encoding="utf-8")
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "features.md").write_text("feat", encoding="utf-8")
    return [".omo/plans/a.md", "docs/features.md"]


def _pending(root: Path, log: Path) -> tuple[manifest.BatchManifest, ApprovalContext, PendingBatch]:
    rels = _seed_repo(root)
    built = manifest.build_manifest(root, "autophagy", rels)
    ctx = ApprovalContext(approval_log=log, owner_id=OWNER, e2e_test_mode=False)
    decision = gate_binding.evaluate(built, context=ctx)
    pending = PendingBatch(
        decision.action_hash, decision.target_id, "msg", "autophagy", "2026-07-24T00:00:00Z", built.files
    )
    return built, ctx, pending


def _drive(tmp_path: Path) -> tuple[DriveClient, FakeGws]:
    fake = FakeGws()
    return DriveClient("gws", tmp_path / "folders.json", runner=fake), fake


def test_upload_fails_closed_without_approval(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _, ctx, pending = _pending(root, tmp_path / "approvals.jsonl")
    drive, fake = _drive(tmp_path)
    with pytest.raises(DriveArchiveError):
        uploader.upload_batch(
            pending, root=root, drive=drive, context=ctx, root_folder_name="Archive",
            cursor_path=tmp_path / "cursor.json", receipts_path=tmp_path / "receipts.jsonl",
        )
    assert not any(call[2] == "+upload" for call in fake.calls)


def test_upload_after_approval_writes_receipts_and_advances_cursor(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    log = tmp_path / "approvals.jsonl"
    built, ctx, pending = _pending(root, log)
    approval.write_manual_reaction(log, pending, OWNER)
    drive, _ = _drive(tmp_path)

    receipts = uploader.upload_batch(
        pending, root=root, drive=drive, context=ctx, root_folder_name="Archive",
        cursor_path=tmp_path / "cursor.json", receipts_path=tmp_path / "receipts.jsonl",
    )
    assert {r["path"] for r in receipts} == {".omo/plans/a.md", "docs/features.md"}
    assert all(r["web_view_link"].startswith("https://") for r in receipts)

    cursor = manifest.load_cursor(tmp_path / "cursor.json")
    assert manifest.diff(built, cursor).files == ()  # re-run would be a no-op
    assert (tmp_path / "receipts.jsonl").read_text(encoding="utf-8").count("web_view_link") == 2


def test_upload_fails_closed_when_file_changed_after_digest(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    log = tmp_path / "approvals.jsonl"
    _, ctx, pending = _pending(root, log)
    approval.write_manual_reaction(log, pending, OWNER)  # approves the ORIGINAL hash
    (root / "docs" / "features.md").write_text("CHANGED AFTER DIGEST", encoding="utf-8")
    drive, fake = _drive(tmp_path)

    with pytest.raises(DriveArchiveError):
        uploader.upload_batch(
            pending, root=root, drive=drive, context=ctx, root_folder_name="Archive",
            cursor_path=tmp_path / "cursor.json", receipts_path=tmp_path / "receipts.jsonl",
        )
    assert not any(call[2] == "+upload" for call in fake.calls)


def test_route_parts_maps_each_class() -> None:
    assert uploader.route_parts("A", ".omo/plans/x.md") == ("A", "plans")
    assert uploader.route_parts("A", ".omo/plans/archive/x.md") == ("A", "plans", "archive")
    assert uploader.route_parts("A", ".omo/notepads/slug/decisions.md") == ("A", "notepads", "slug")
    assert uploader.route_parts("A", "docs/features.md") == ("A", "features")
    assert uploader.route_parts("A", "docs/qa/E11/00-note.txt") == ("A", "qa", "E11")
    assert uploader.route_parts("A", "docs/patch/2026-07-24-x.md") == ("A", "patch")
