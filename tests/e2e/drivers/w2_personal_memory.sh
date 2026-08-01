#!/usr/bin/env bash
# W2-6 scenario driver: pushes the remote actuator + fixtures to the agent
# account selected by E2E_REMOTE_HOST, runs the bank UNATTENDED under E2E_TEST_MODE=1, then
# judges the emitted observations against the scenario YAML expect blocks.
#
# Usage: w2_personal_memory.sh <scenario.yaml> <report_dir>
# Exit:  0 = every case matched its expected observables, 1 = mismatch/error.
set -euo pipefail

SCENARIO="$(readlink -f "$1")"
REPORT_DIR="$(mkdir -p "$2" && readlink -f "$2")"
ROOT="$(cd "$(dirname "$SCENARIO")/../../.." && pwd)"
DRIVERS="$ROOT/tests/e2e/drivers"
FIXTURES="$ROOT/tests/e2e/fixtures/w2-personal-memory"
for key in E2E_REMOTE_HOST E2E_PRIMARY_ACCOUNT; do
  [[ -n "${!key:-}" ]] || { echo "SKIP w2-personal-memory: missing $key (requires SSH/sudo, runtime CLIs, Kanban, and retrieval node)"; exit 77; }
done
HOST="$E2E_REMOTE_HOST"
ACCOUNT="$E2E_PRIMARY_ACCOUNT"
PUSH_DIR=".cache/w2e6-bank-push"
RUN_TIMEOUT=900

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
cp "$DRIVERS/w2_personal_memory_remote.py" "$stage/remote.py"
mkdir -p "$stage/fixtures"
cp "$FIXTURES"/* "$stage/fixtures/"

# Push (tar over ssh/sudo — avoids nested-quoting and stdin-eating pitfalls).
tar -C "$stage" -cf - . | ssh "$HOST" "sudo -n -u $ACCOUNT -H bash -c \
  'umask 077; rm -rf $HOME/$PUSH_DIR; mkdir -p $HOME/$PUSH_DIR; tar -xf - -C $HOME/$PUSH_DIR'"

# Run unattended (stdin closed; E2E_TEST_MODE only on this process tree).
run_log="$REPORT_DIR/remote-run.log"
set +e
timeout "$RUN_TIMEOUT" ssh "$HOST" "sudo -n -u $ACCOUNT -H bash -lc \
  'set -euo pipefail; cd ~; E2E_TEST_MODE=1 python3 $HOME/$PUSH_DIR/remote.py \
   --fixtures $HOME/$PUSH_DIR/fixtures'" </dev/null >"$run_log" 2>&1
run_rc=$?
set -e

# Remote scratch cleanup regardless of outcome.
ssh "$HOST" "sudo -n -u $ACCOUNT -H rm -rf \$HOME/$PUSH_DIR" </dev/null || true

if [[ $run_rc -ne 0 ]]; then
  echo "FAIL w2-personal-memory: remote actuator rc=$run_rc (see $run_log)"
  exit 1
fi

sed -n 's/^OBS-JSON: //p' "$run_log" | head -1 >"$REPORT_DIR/observations.json"
if [[ ! -s "$REPORT_DIR/observations.json" ]]; then
  echo "FAIL w2-personal-memory: no OBS-JSON line in remote output (see $run_log)"
  exit 1
fi

python3 "$DRIVERS/judge_expectations.py" "$SCENARIO" \
  "$REPORT_DIR/observations.json" "$REPORT_DIR/verdict.txt"
