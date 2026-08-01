#!/usr/bin/env bash
# W3-6 scenario driver (w3-calendar): pushes the remote actuator to the agent
# account, runs it UNATTENDED (per-run HMAC secret, E2E mode scoped to the
# actuator process tree only), then judges the emitted observations.
#
# Usage: w3_calendar.sh <scenario.yaml> <report_dir>
# Exit:  0 = every case matched its expected observables, 1 = mismatch/error.
set -euo pipefail

SCENARIO="$(readlink -f "$1")"
REPORT_DIR="$(mkdir -p "$2" && readlink -f "$2")"
ROOT="$(cd "$(dirname "$SCENARIO")/../../.." && pwd)"
DRIVERS="$ROOT/tests/e2e/drivers"
for key in E2E_REMOTE_HOST E2E_PRIMARY_ACCOUNT E2E_APPROVAL_LOG; do
  [[ -n "${!key:-}" ]] || { echo "SKIP w3-calendar: missing $key (requires SSH/sudo, calendar services, and reminder poller)"; exit 77; }
done
HOST="$E2E_REMOTE_HOST"
ACCOUNT="$E2E_PRIMARY_ACCOUNT"
PUSH_DIR=".cache/w36-calendar-push"
RUN_TIMEOUT=600

# Push actuator + generate the per-run injection secret (agent-home, 600).
ssh "$HOST" "sudo -n -u $ACCOUNT -H bash -c \
  'umask 077; rm -rf $HOME/$PUSH_DIR; mkdir -p $HOME/$PUSH_DIR; cat > $HOME/$PUSH_DIR/remote.py'" \
  < "$DRIVERS/w3_calendar_remote.py"
ssh "$HOST" "sudo -n -u $ACCOUNT -H bash -c \
  'umask 077; openssl rand -hex 32 > $HOME/$PUSH_DIR/.secret'" </dev/null

run_log="$REPORT_DIR/remote-run.log"
set +e
timeout "$RUN_TIMEOUT" ssh "$HOST" "sudo -n -u $ACCOUNT -H bash -lc \
  'set -euo pipefail; cd ~; python3 $HOME/$PUSH_DIR/remote.py \
   --secret-file $HOME/$PUSH_DIR/.secret --approvals-log '"$(printf '%q' "$E2E_APPROVAL_LOG")"'" </dev/null >"$run_log" 2>&1
run_rc=$?
set -e

ssh "$HOST" "sudo -n -u $ACCOUNT -H rm -rf \$HOME/$PUSH_DIR" </dev/null || true

if [[ $run_rc -ne 0 ]]; then
  echo "FAIL w3-calendar: remote actuator rc=$run_rc (see $run_log)"
  exit 1
fi

sed -n 's/^OBS-JSON: //p' "$run_log" | head -1 >"$REPORT_DIR/observations.json"
if [[ ! -s "$REPORT_DIR/observations.json" ]]; then
  echo "FAIL w3-calendar: no OBS-JSON line in remote output (see $run_log)"
  exit 1
fi

python3 "$DRIVERS/judge_expectations.py" "$SCENARIO" \
  "$REPORT_DIR/observations.json" "$REPORT_DIR/verdict.txt"
