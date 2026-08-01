#!/usr/bin/env bash
set -euo pipefail
for key in E2E_REMOTE_HOST E2E_PRIMARY_ACCOUNT E2E_PEER_ACCOUNT; do
  [[ -n "${!key:-}" ]] || { echo "SKIP gate-interop: missing $key (requires SSH/sudo and both interop runtimes)"; exit 77; }
done
readonly HOST="$E2E_REMOTE_HOST"
readonly DRIVER="\$HOME/.hermes/interop/gate_driver.py"
run() { local account="$1" phase="$2" round="$3"; ssh "$HOST" "sudo -n -u $account -H bash -lc 'set -a; . \$HOME/.env.secrets; set +a; export PYTHONPATH=\$HOME/.hermes/interop_runtime; python3 $DRIVER $account $phase $round'"; }
failed=0
for round in 1 2 3; do
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  a="$(run "$E2E_PRIMARY_ACCOUNT" a "$round" || true)"
  b1="$(run "$E2E_PRIMARY_ACCOUNT" b "$round" || true)"
  b2="$(run "$E2E_PEER_ACCOUNT" b "$round" || true)"
  b3="$(run "$E2E_PRIMARY_ACCOUNT" b "$round" || true)"
  if [[ "$a" != *'"response": true, "dm": true'* || "$b2" != *'"parsed_other": true'* || "$b3" != *'"parsed_other": true'* ]]; then failed=1; fi
  printf 'round=%s timestamp=%s A=%s B-agent-post=%s B-peer=%s B-agent-parse=%s\n' "$round" "$timestamp" "$a" "$b1" "$b2" "$b3"
  [[ "$round" == 3 ]] || sleep 61
done
exit "$failed"
