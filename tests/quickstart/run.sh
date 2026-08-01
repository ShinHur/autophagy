#!/usr/bin/env bash

set -euo pipefail

fail() {
    printf 'QUICKSTART-FAIL: %s\n' "$*" >&2
    exit 1
}

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/aq.XXXXXX")"
work_repo="$work_dir/repo"

cleanup() {
    chmod -R u+rwX "$work_dir" 2>/dev/null || true
    rm -rf "$work_dir"
}
trap cleanup EXIT

mkdir -p "$work_dir/home" "$work_dir/tmp" "$work_repo"
cp -a "$repo_root/." "$work_repo/" || fail 'could not create isolated quickstart copy'
export HOME="$work_dir/home"
export TMPDIR="$work_dir/tmp"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="$work_dir/pycache"
export PYTEST_ADDOPTS='-p no:cacheprovider'

cd "$work_repo"

command -v python3 >/dev/null 2>&1 || fail 'python3 is required'
command -v bash >/dev/null 2>&1 || fail 'bash is required'
command -v git >/dev/null 2>&1 || fail 'git is required'

python3 - <<'PY' || fail 'Python 3.12 or newer is required'
import sys

if sys.version_info < (3, 12):
    raise SystemExit(1)
PY

config_path="$work_repo/.env"
cp .env.example "$config_path" || fail 'could not copy .env.example'
python3 - "$config_path" <<'PY' || fail 'could not apply synthetic quickstart configuration'
from pathlib import Path
import sys

path = Path(sys.argv[1])
values = {
    "DISCORD_OWNER_ID": "100000000000000001",
    "DISCORD_GUILD_ID": "100000000000000002",
    "DISCORD_OWNER_DM_CHANNEL_ID": "100000000000000003",
    "DISCORD_APPROVALS_CHANNEL_ID": "100000000000000004",
    "DISCORD_BOT_USER_ID_AGENT": "100000000000000005",
    "DISCORD_BOT_USER_ID_PEER": "100000000000000006",
}
lines = []
for line in path.read_text(encoding="utf-8").splitlines():
    key, separator, _ = line.partition("=")
    lines.append(f"{key}={values[key]}" if separator and key in values else line)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

python3 -m pytest --basetemp "$work_dir/pytest" tests/unit || fail 'unit test suite failed'
find . -name '__pycache__' -type d -prune -exec rm -rf {} +
find . -name '*.pyc' -delete
rm -rf .pytest_cache
python3 tools/repo_scan.py --profile public-generic --root . || fail 'public hygiene scan failed'
python3 tools/repo_scan.py --profile docs-claims --root . || fail 'documentation-claims scan failed'

topics_output="$(TOPICS_STATE_FILE="$work_dir/topics.yaml" python3 skills/topics/scripts/topics_cli.py list)" \
    || fail 'read-only topics CLI failed'
if [ "$topics_output" != 'TOPICS-EMPTY 등록된 주제가 없습니다.' ]; then
    fail "unexpected read-only topics CLI output: $topics_output"
fi
printf '%s\n' "$topics_output"

gate_output="$(python3 - "$config_path" <<'PY'
from pathlib import Path
import sys

from automation.interop.external_effect_gate import (
    ApprovalContext,
    ToolCall,
    evaluate_tool_call,
    load_denylist,
)

config = dict(
    line.split("=", 1)
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    if "=" in line and not line.startswith("#")
)
decision = evaluate_tool_call(
    ToolCall("bash", {"command": "gws gmail +send --to synthetic@example.invalid"}),
    load_denylist("configs/external-effect-tools.yaml"),
    ApprovalContext(approval_log=None, owner_id=config["DISCORD_OWNER_ID"], e2e_test_mode=False),
)
print(
    f"external_effect={decision.external_effect} "
    f"allowed={decision.allowed} reason={decision.reason}"
)
PY
)" || fail 'approval gate demonstration failed'
if [ "$gate_output" != 'external_effect=True allowed=False reason=approval_required' ]; then
    fail "unexpected approval gate output: $gate_output"
fi
printf '%s\n' "$gate_output"

printf 'QUICKSTART-OK\n'
