#!/usr/bin/env bash
set -euo pipefail

umask 077
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${REGRESSION_BANK_HOST_B:?REGRESSION_BANK_HOST_B is required — see .env.example}"
: "${REGRESSION_BANK_HOST_A:?REGRESSION_BANK_HOST_A is required — see .env.example}"
: "${REGRESSION_BANK_REMOTE_USER:?REGRESSION_BANK_REMOTE_USER is required — see .env.example}"
: "${REGRESSION_BANK_HARNESS_ROOT:?REGRESSION_BANK_HARNESS_ROOT is required — see .env.example}"
: "${REGRESSION_BANK_RUNNER_PATH:?REGRESSION_BANK_RUNNER_PATH is required — see .env.example}"
: "${REGRESSION_BANK_LOG_DIR:?REGRESSION_BANK_LOG_DIR is required — see .env.example}"
: "${REGRESSION_BANK_RUNTIME_DIR:?REGRESSION_BANK_RUNTIME_DIR is required — see .env.example}"
: "${REGRESSION_BANK_AGENT_BIN_DIR:?REGRESSION_BANK_AGENT_BIN_DIR is required — see .env.example}"
HOST4="$REGRESSION_BANK_HOST_B"
HOST0="$REGRESSION_BANK_HOST_A"
TARGET4="${REGRESSION_BANK_REMOTE_USER}@$HOST4"
TARGET0="${REGRESSION_BANK_REMOTE_USER}@$HOST0"
HARNESS_ROOT="$REGRESSION_BANK_HARNESS_ROOT"
RUNNER_PATH="$REGRESSION_BANK_RUNNER_PATH"
WEEKLY_LINE="15 3 * * 1 $RUNNER_PATH >> $REGRESSION_BANK_LOG_DIR/cron.log 2>&1"
LEGACY_CRON_ID=56002e306644

rsync -a --delete \
  --exclude='.git/' \
  --exclude='configs/rag/' \
  --exclude='**/.venv/' \
  --exclude='**/node_modules/' \
  --exclude='**/__pycache__/' \
  --exclude='*.pyc' \
  --exclude='logs/' \
  --exclude='.omo/' \
  "$repo_root/" "$TARGET4:$HARNESS_ROOT/"
ssh "$TARGET4" "chmod 700 $HARNESS_ROOT; install -d -m 700 $(dirname "$RUNNER_PATH") $REGRESSION_BANK_LOG_DIR"

scp "$repo_root/automation/regression_bank/remote_bank_runner.sh" "$TARGET4:$RUNNER_PATH"
ssh "$TARGET4" "chmod 700 $RUNNER_PATH"

existing_crontab="$(mktemp)"
filtered_crontab="$(mktemp)"
trap 'rm -f "$existing_crontab" "$filtered_crontab"' EXIT
ssh "$TARGET4" 'crontab -l 2>/dev/null || true' >"$existing_crontab"
awk -v weekly_line="$WEEKLY_LINE" \
  '$0 != "CRON_TZ=Asia/Seoul" && $0 != weekly_line { print }' \
  "$existing_crontab" >"$filtered_crontab"
{
  printf '%s\n' 'CRON_TZ=Asia/Seoul'
  printf '%s\n' "$WEEKLY_LINE"
  cat "$filtered_crontab"
} | ssh "$TARGET4" 'crontab -'

ssh "$TARGET0" "sudo -n -u agent -H bash -c 'umask 077; mkdir -p $REGRESSION_BANK_RUNTIME_DIR; cat > $REGRESSION_BANK_RUNTIME_DIR/bank_state.py; chmod 600 $REGRESSION_BANK_RUNTIME_DIR/bank_state.py'" \
  <"$repo_root/automation/regression_bank/bank_state.py"

ssh "$TARGET0" "sudo -n -u agent -H env PATH=$REGRESSION_BANK_AGENT_BIN_DIR:\$PATH hermes cron remove $LEGACY_CRON_ID 2>/dev/null || true"

printf '%s\n' '=== deployment verification ==='
ssh "$TARGET4" "stat -c '%A %U %n' $HARNESS_ROOT; stat -c '%A %U %n' $RUNNER_PATH; crontab -l"
