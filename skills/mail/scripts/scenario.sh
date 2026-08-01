#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cat > "$work/backend.py" <<'PY'
import json
import os
import pathlib
import sys

request = json.loads(sys.stdin.read())
operation = request["operation"]
if operation == "list":
    response = {
        "operation": "list",
        "status": "ok",
        "synced": request["sync"],
        "mails": [{
            "message_id": "message-1",
            "folder": "inbox",
            "subject": "Synthetic subject",
            "sender": "sender@example.invalid",
            "received_at": "2030-01-02T03:04:05Z",
        }],
    }
elif operation == "get":
    response = {
        "operation": "get",
        "status": "ok",
        "mail": {
            "message_id": request["message_id"],
            "folder": "inbox",
            "subject": "Synthetic subject",
            "sender": "sender@example.invalid",
            "received_at": "2030-01-02T03:04:05Z",
            "body": "Synthetic body",
        },
    }
elif operation == "status":
    response = {
        "operation": "status",
        "status": "ok",
        "available": True,
        "account": "site",
        "message": "ready",
    }
elif operation == "resolve":
    response = {
        "operation": "resolve",
        "status": "ok",
        "query": request["query"],
        "candidates": [{
            "kind": "directory",
            "name": "Example Person",
            "email": "person@example.invalid",
            "organization": "Example Organization",
        }],
    }
elif operation == "send":
    log = os.environ.get("SCENARIO_SEND_LOG")
    if log:
        pathlib.Path(log).write_text("sent", encoding="utf-8")
    response = {
        "operation": "send",
        "status": "submitted",
        "message_id": "sent-1",
        "verified": True,
        "attachment_count": 0,
        "attachment_manifest_sha256": None,
    }
else:
    raise SystemExit(2)
print(json.dumps(response, separators=(",", ":"), sort_keys=True))
PY

python3 - "$work/config.json" "$work/backend.py" <<'PY'
import json
import sys

path, backend = sys.argv[1:]
with open(path, "w", encoding="utf-8") as stream:
    json.dump(
        {
            "contract_version": 1,
            "backend_id": "mail.example.invalid",
            "organization": "Example Organization",
            "command": [sys.executable, backend],
            "timeout_seconds": 30,
        },
        stream,
    )
PY

export AUTOPHAGY_REPO_ROOT="$repo_root"
export SITE_MAIL_BACKEND_CONFIG="$work/config.json"

python3 "$script_dir/mail_wrapper.py" list --limit 1 --sync > "$work/list.json"
python3 "$script_dir/mail_wrapper.py" get message-1 --body > "$work/get.json"
python3 "$script_dir/mail_wrapper.py" status > "$work/status.json"
python3 "$script_dir/mail_wrapper.py" resolve --name "Example Person" > "$work/resolve.json"

python3 - "$script_dir" "$work" <<'PY'
import json
import os
import pathlib
import subprocess
import sys

script_dir = pathlib.Path(sys.argv[1])
work = pathlib.Path(sys.argv[2])
sys.path.insert(0, str(script_dir))
import site_mail_backend

listed = json.loads((work / "list.json").read_text(encoding="utf-8"))
fetched = json.loads((work / "get.json").read_text(encoding="utf-8"))
health = json.loads((work / "status.json").read_text(encoding="utf-8"))
resolved = json.loads((work / "resolve.json").read_text(encoding="utf-8"))
assert listed["mails"][0]["uid"] == fetched["mail"]["uid"] == "message-1"
assert health["available"] is True
assert resolved["candidates"][0]["email"] == "person@example.invalid"

approved_hash = site_mail_backend.config_sha256()
request = site_mail_backend.SendRequest(
    to="recipient@example.invalid",
    subject="Synthetic subject",
    body="Synthetic body",
    attachments=(),
    attachment_manifest_sha256=None,
)
argv = site_mail_backend.build_send_argv(request, approved_hash)
config_path = pathlib.Path(os.environ["SITE_MAIL_BACKEND_CONFIG"])
config = json.loads(config_path.read_text(encoding="utf-8"))
config["backend_id"] = "replacement.example.invalid"
config_path.write_text(json.dumps(config), encoding="utf-8")
environment = {**os.environ, "SCENARIO_SEND_LOG": str(work / "send.log")}
result = subprocess.run(argv, capture_output=True, text=True, check=False, env=environment)
assert result.returncode == 6
assert not (work / "send.log").exists()
PY

printf '%s\n' 'SCENARIO-PASS'
