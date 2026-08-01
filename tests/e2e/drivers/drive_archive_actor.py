"""E11 drive-archive E2E actor: offline batch-digest -> owner ✅ -> gated upload,
plus ⛔ cancel + unknown-hash fail-closed, plus supersede/dedupe of the live digest.

Fully offline against temp dirs + stub gws/Discord transports (zero network,
zero production paths, zero real sends). Drives the production modules exactly as
the cron producer + reaction watcher would. Emits one flat observation map per
case as ``OBS-JSON: {...}``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

type ObservationValue = bool | int | str | None

APPROVE = "\u2705"
CANCEL = "\u26d4"
OWNER = "100000000000000011"

GWS_STUB = (
    "#!/bin/sh\n"
    'case "$*" in\n'
    "  *\"files list\"*) echo '{\"files\":[]}' ;;\n"
    "  *\"files create\"*) echo '{\"id\":\"fold-1\"}' ;;\n"
    "  *\"+upload\"*) echo '{\"id\":\"file-1\"}' ;;\n"
    "  *\"files update\"*) echo '{\"id\":\"file-1\"}' ;;\n"
    "  *\"files get\"*) echo '{\"webViewLink\":\"https://drive.google.com/file/d/file-1/view\"}' ;;\n"
    "esac\n"
)


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "automation.drive_archive.sync_cli", *args],
        env=env, capture_output=True, text=True, timeout=300, check=False,
    )


def _watch(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "automation.drive_archive.confirm_reaction_watch"],
        env=env, capture_output=True, text=True, timeout=300, check=False,
    )


def _seed_reaction(discord_dir: Path, message_id: str, emoji: str) -> None:
    (discord_dir / f"{message_id}.reactions.json").write_text(
        json.dumps({emoji: [[OWNER, False]]}), encoding="utf-8"
    )


def _upload_count(log: Path) -> int:
    return log.read_text(encoding="utf-8").count("+upload") if log.exists() else 0


def _captured_int(pattern: str, text: str) -> int:
    match = re.search(pattern, text)
    return int(match.group(1)) if match is not None else -1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    real_root = Path(parser.parse_args().root).resolve()
    sys.path.insert(0, str(real_root))
    from automation.drive_archive.approval_adapter import approval_key
    from automation.interop.approval_lease import FileKeyLease
    from automation.interop.external_effect_gate import _has_valid_approval

    obs: dict[str, dict[str, ObservationValue]] = {}
    with tempfile.TemporaryDirectory(prefix="e11-drive-archive-") as tmp:
        base = Path(tmp)
        fake = base / "repo"
        state = base / "state"
        discord = base / "discord"
        for path in (fake / ".omo/plans", fake / "docs/qa/E11", fake / "docs/patch", state, discord):
            path.mkdir(parents=True)
        (fake / "automation").symlink_to(real_root / "automation")
        (fake / ".omo/plans/autophagy-agents.md").write_text("# plan\n", encoding="utf-8")
        (fake / "docs/features.md").write_text("# features\n", encoding="utf-8")
        (fake / "docs/qa/E11/00-note.txt").write_text("qa\n", encoding="utf-8")
        (fake / "docs/patch/2026-07-24-demo.md").write_text("# patch\n", encoding="utf-8")
        (base / "config.json").write_text(json.dumps({"owner_id": OWNER}), encoding="utf-8")
        gws = base / "gws-stub"
        gws.write_text(GWS_STUB, encoding="utf-8")
        gws.chmod(0o755)
        gws_log = base / "gws-calls.log"

        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(base / "home"),
            "PYTHONPATH": str(fake),
            "AUTOPHAGY_REPO_ROOT": str(fake),
            "DRIVE_ARCHIVE_STATE_DIR": str(state),
            "DRIVE_ARCHIVE_APPROVAL_LOG": str(state / "approvals.jsonl"),
            "DRIVE_ARCHIVE_DENYLIST": str(real_root / "configs" / "external-effect-tools.yaml"),
            "INTEROP_CONFIG": str(base / "config.json"),
            "DRIVE_ARCHIVE_DISCORD_STUB": str(discord),
            "DRIVE_ARCHIVE_GWS_BIN": str(gws),
            "GWS_STUB_STATE": str(base / "gws-state.json"),
            "GWS_STUB_LOG": str(gws_log),
        }

        # --- case 1: happy batch-digest -> ✅ -> upload -----------------------
        plan = _run(env, "plan")
        plan_count = _captured_int(r"PLAN files=(\d+)", plan.stdout)
        request = _run(env, "request")
        hash_match = re.search(r"SYNC-REQUESTED hash=(\S+) files=(\d+) message=(\S+)", request.stdout)
        action_hash = hash_match.group(1) if hash_match else ""
        message_id = hash_match.group(3) if hash_match else ""
        digest_text = (discord / f"{message_id}.json").read_text(encoding="utf-8") if message_id else ""
        pending_files = list((state / "pending").glob("*.json"))

        _seed_reaction(discord, message_id, APPROVE)
        _watch(env)

        approval_log = state / "approvals.jsonl"
        approval_written = approval_log.exists()
        approval_ok = approval_written and _has_valid_approval(
            approval_log, action_hash, "tool:drive_archive_batch_upload:drive_archive.batch_upload", OWNER, False
        )
        receipts = (state / "receipts.jsonl").read_text(encoding="utf-8").splitlines() if (state / "receipts.jsonl").exists() else []
        cursor = json.loads((state / "cursor.json").read_text(encoding="utf-8")) if (state / "cursor.json").exists() else {}
        dm_files = list(discord.glob("dm*.dm.json"))
        status = _run(env, "status")
        status_pending = _captured_int(r"STATUS pending=(\d+)", status.stdout)
        rerun = _run(env, "request")

        obs["batch_upload_happy"] = {
            "plan_file_count": plan_count,
            "request_posted": bool(action_hash),
            "digest_has_hash": action_hash in digest_text,
            "pending_stored": len(pending_files) == 1,
            "approval_written": approval_written,
            "approval_accepted_by_gate": bool(approval_ok),
            "files_uploaded": len(receipts),
            "receipts_have_links": bool(receipts) and all("drive.google.com" in line for line in receipts),
            "cursor_advanced": len(cursor) == 4,
            "owner_dm_sent": len(dm_files) >= 1,
            "status_pending_after": status_pending,
            "rerun_no_changes": "NO-CHANGES" in rerun.stdout,
            "real_network_sends": 0,
            "error": None,
        }

        # --- case 2: ⛔ cancel + unknown-hash fail-closed ---------------------
        (fake / "docs/features.md").write_text("# features v2\n", encoding="utf-8")
        cancel_request = _run(env, "request")
        cancel_match = re.search(r"SYNC-REQUESTED hash=(\S+) files=(\d+) message=(\S+)", cancel_request.stdout)
        cancel_files = int(cancel_match.group(2)) if cancel_match else -1
        cancel_message = cancel_match.group(3) if cancel_match else ""
        uploads_before = _upload_count(gws_log)
        _seed_reaction(discord, cancel_message, CANCEL)
        _watch(env)
        uploads_after = _upload_count(gws_log)
        cancel_status = _run(env, "status")
        cancel_pending = _captured_int(r"STATUS pending=(\d+)", cancel_status.stdout)
        unknown = _run(env, "upload", "--hash", "sha256:deadbeef")

        obs["cancel_and_fail_closed"] = {
            "cancel_request_files": cancel_files,
            "cancel_upload_delta": uploads_after - uploads_before,
            "cancel_pending_cleared": cancel_pending == 0,
            "unknown_hash_refused": unknown.returncode == 1 and "UPLOAD-REFUSED" in unknown.stdout,
            "error": None,
        }

        # --- case 3: exactly ONE live approval message per project ------------
        first = _run(env, "request")
        first_match = re.search(r"SYNC-REQUESTED hash=(\S+) files=(\d+) message=(\S+)", first.stdout)
        msg_a = first_match.group(3) if first_match else ""
        (fake / "docs/qa/E11/01-supersede.txt").write_text("supersede\n", encoding="utf-8")
        superseded = _run(env, "request")
        second_match = re.search(r"SYNC-REQUESTED hash=(\S+) files=(\d+) message=(\S+)", superseded.stdout)
        hash_b = second_match.group(1) if second_match else ""
        msg_b = second_match.group(3) if second_match else ""
        repeat = _run(env, "request")

        with FileKeyLease(state / "approval-leases").hold(approval_key("autophagy-agents")) as owned:
            assert owned
            (fake / "docs/qa/E11/02-inflight.txt").write_text("inflight\n", encoding="utf-8")
            deferred = _run(env, "request")

        pending_after = list((state / "pending").glob("*.json"))
        pending_hash = (
            str(json.loads(pending_after[0].read_text(encoding="utf-8")).get("action_hash", ""))
            if len(pending_after) == 1
            else ""
        )

        obs["supersede_and_dedupe"] = {
            "superseded_message_deleted": bool(msg_a) and not (discord / f"{msg_a}.json").exists(),
            "new_message_posted": bool(msg_b) and (discord / f"{msg_b}.json").exists(),
            "supersede_token": "SYNC-SUPERSEDED reason=batch-changed" in superseded.stdout,
            "pending_records_after": len(pending_after) == 1,
            "pending_hash_is_latest": bool(hash_b) and pending_hash == hash_b,
            "repeat_posts_nothing": "SYNC-PENDING" in repeat.stdout and "SYNC-REQUESTED" not in repeat.stdout,
            "claim_defers": "SYNC-DEFERRED reason=batch-in-flight" in deferred.stdout and "SYNC-REQUESTED" not in deferred.stdout,
            "error": None,
        }

    print("OBS-JSON: " + json.dumps(obs, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
