#!/usr/bin/env bash
# automation/deploy-skill.sh — W1-8 skill deploy pipeline (v2.4 managed activation review gate).
#
# Pipeline (enforced order, fail-closed):
#   ① SANDBOX  — skill copied to the *peer* instance: every shipped module is first
#                parsed by the peer's hermes runtime CPython (py3.11 — the cron
#                interpreter, NOT the dev/CI py3.12), then its scenario runs with
#                DUMMY secrets only (env -i isolation). Any failure blocks the
#                pipeline BEFORE the approval stage (exit 2).
#   ② REVIEW    — deterministic, hash-bound review via automation/skill_review.py
#                records PASS/FAIL on the agent. The peer's already-successful
#                DUMMY-secret scenario output is reused; untrusted code does
#                not execute a second time on agent. Any failure exits 5.
#   ③ REQUEST + PEER-ATTEST — the agent posts the request; peer independently
#                reviews its retained sandbox copy and replies as its own bot.
#                Owner ✅ (or E2E injection) AND peer attestation are required.
#   ④ MOUNT    — current digest, agent review, peer attestation, and owner
#                approval are all rechecked before the reviewed artifact is
#                published by the root-owned store helper; Hermes discovery and invoke smoke run.
#
# Usage:
#   deploy-skill.sh <skill> [--request-only] [--approve-only] [--fresh] [--sandbox-only] [--remove]
#                           [--activate-managed <quarantine-dir>]
#
# Env:
#   DEPLOY_SSH_HOST      ssh host running agent/peer (required; "" = this node)
#   AUTOPHAGY_DEPLOY_ROOT  absolute deploy-checkout root on the node (required)
#   AUTOPHAGY_SKILLS_ROOT  absolute live skills root on the node (required)
#   SKILL_SRC_DIR        override skill source dir (default <repo>/skills/<skill>)
#   E2E_TEST_MODE=1      regression-only signed-injection approval path. NEVER
#                        set on the production agent gateway (its unit refuses it).
#   SKILL_PROPOSAL_SOURCE  "auto" enables the max-3-per-week proposal limit.
#   APPROVAL_MESSAGE_ID  check an existing request (requires DEPLOY_NONCE too).
#   DEPLOY_NONCE         nonce bound to APPROVAL_MESSAGE_ID.
#
# Exit codes: 0 ok | 1 approval absent/invalid (no mount) | 2 sandbox block
#             3 weekly auto-proposal rate limit | 4 usage/env error
#             5 review missing/failed/hash-mismatched (no mount)
#             6 approval-lifecycle refusal (an existing live request is preserved)
#             8 another execution holds this skill's refresh-to-consume lease
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIRROR_CHECKOUT="${AUTOPHAGY_DEPLOY_ROOT:?AUTOPHAGY_DEPLOY_ROOT is required — see .env.example}"
: "${AUTOPHAGY_SKILLS_ROOT:?AUTOPHAGY_SKILLS_ROOT is required — see .env.example}"
STORE_ROOT="$(dirname "$AUTOPHAGY_SKILLS_ROOT")"
RELEASE_CURRENT="$(dirname "$MIRROR_CHECKOUT")/autophagy-agent-current"
# DG-4: resolve the runtime root (release `current`, else the resident mirror).
# The shared resolver is handed the SAME two paths this script uses, so one
# deployment configuration drives both and they can never disagree.
RUNTIME_RELEASE_CURRENT="$RELEASE_CURRENT"
RUNTIME_MIRROR_CHECKOUT="$MIRROR_CHECKOUT"
# shellcheck source=automation/runtime_root.sh
source "$REPO_ROOT/automation/runtime_root.sh"
# Resolve the runtime root once (release `current` if present, else the mirror);
# the ABI scan below runs the shared library from wherever the runtime truly is.
RUNTIME_ROOT="$(autophagy_runtime_root)"
# The trust-critical peer_attest / execution-lock / scenario run via `run_as` ON
# THE NODE, so their runtime root must be resolved node-side (not from the
# workstation-resolved $RUNTIME_ROOT, which would stat a node path on the wrong
# host). This snippet is embedded verbatim in those node-side shells and prefers
# the release `current` symlink, else the resident mirror (a no-op until DG-5).
NODE_RUNTIME_ROOT_SNIPPET="node_runtime_root(){ if [ -e $RELEASE_CURRENT ]; then printf %s $RELEASE_CURRENT; else printf %s $MIRROR_CHECKOUT; fi; }"
SSH_HOST="${DEPLOY_SSH_HOST?DEPLOY_SSH_HOST is required (empty = this node) — see .env.example}"
[[ "$(hostname -s 2>/dev/null)" == "$SSH_HOST" ]] && SSH_HOST=""
MANAGED_PROVENANCE_FILE=""
MANAGED_PROVENANCE_REMOTE=""

log() { printf '[deploy-skill] %s\n' "$*" >&2; }
die() { log "ERROR: $1"; exit "${2:-4}"; }

run_as() { # run_as <account> <script>  (stdin passes through for file pushes)
  local acct="$1" script="$2"
  if [[ -n "$SSH_HOST" ]]; then
    ssh "$SSH_HOST" "sudo -n -u $acct -H bash -c $(printf '%q' "$script")"
  else
    sudo -n -u "$acct" -H bash -c "$script"
  fi
}

push_skill() { # push_skill <account> <src_dir> <name>
  local acct="$1" src="$2" name="$3"
  [[ "$(basename "$src")" == "$name" ]] || die "source dir basename must equal skill name"
  tar -C "$(dirname "$src")" --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' -czf - "$name" \
    | run_as "$acct" "rm -rf \"\$HOME/.hermes/skills/$name\" && mkdir -p \"\$HOME/.hermes/skills\" && tar -xzf - -C \"\$HOME/.hermes/skills\""
}

install_reviewed_skill() {
  local src="$1" name="$2" digest="$3"
  if [[ -n "$SSH_HOST" ]]; then
    tar -C "$(dirname "$src")" --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' -czf - "$name" \
      | ssh -o ClearAllForwardings=yes "$SSH_HOST" "sudo -n /usr/local/libexec/autophagy-install-skill install --skill '$name' --hash '$digest'"
  else
    tar -C "$(dirname "$src")" --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' -czf - "$name" \
      | sudo -n /usr/local/libexec/autophagy-install-skill install --skill "$name" --hash "$digest"
  fi
}

install_managed_skill() {
  local src="$1" publisher="$2" name="$3" digest="$4"
  if [[ -n "$SSH_HOST" ]]; then
    tar -C "$(dirname "$src")" --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' -czf - "$name" \
      | ssh -o ClearAllForwardings=yes "$SSH_HOST" "sudo -n /usr/local/libexec/autophagy-install-skill install-managed --publisher '$publisher' --skill '$name' --hash '$digest'"
  else
    tar -C "$(dirname "$src")" --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' -czf - "$name" \
      | sudo -n /usr/local/libexec/autophagy-install-skill install-managed --publisher "$publisher" --skill "$name" --hash "$digest"
  fi
}

remove_live_skill() {
  local name="$1"
  if [[ -n "$SSH_HOST" ]]; then
    ssh -o ClearAllForwardings=yes "$SSH_HOST" "sudo -n /usr/local/libexec/autophagy-install-skill remove --skill '$name'"
  else
    sudo -n /usr/local/libexec/autophagy-install-skill remove --skill "$name"
  fi
}

stage_review_source() { # stage_review_source <src_dir> <name> <digest>
  local src="$1" name="$2" digest="$3"
  tar -C "$(dirname "$src")" --exclude='__pycache__' --exclude='*.pyc' --exclude='*.pyo' -czf - "$name" \
    | run_as agent "rm -rf \"\$HOME/.hermes/skill-gate/review-staging/$name\" && mkdir -p \"\$HOME/.hermes/skill-gate/review-staging/$name/$digest\" && tar -xzf - -C \"\$HOME/.hermes/skill-gate/review-staging/$name/$digest\""
}

save_review_scenario() { # save_review_scenario <output> <name> <digest>
  local output="$1" name="$2" digest="$3"
  printf '%s' "$output" \
    | run_as agent "umask 077; mkdir -p \"\$HOME/.hermes/skill-gate/review-staging/$name/$digest\"; cat > \"\$HOME/.hermes/skill-gate/review-staging/$name/$digest/scenario.out\"; chmod 600 \"\$HOME/.hermes/skill-gate/review-staging/$name/$digest/scenario.out\""
}

cleanup_review_staging() { # cleanup_review_staging <name>
  run_as agent "rm -rf \"\$HOME/.hermes/skill-gate/review-staging/$1\"" || true
}

skill_digest() { # deterministic content hash of the skill dir
  PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 -c 'from pathlib import Path; from automation.skill_review import skill_digest; import sys; print(skill_digest(Path(sys.argv[1])))' "$1"
}

hermes_lists_skill() { # hermes_lists_skill <account> <name> -> exit 0 when listed
  run_as "$1" "cd ~ && export PATH=\"\$HOME/.local/bin:\$PATH\" && hermes skills list 2>/dev/null | grep -Fq \"$2\""
}

gate() { # gate <extra-env> <gate-args...> — runs skill_gate.py as agent with its secrets
  local extra="$1"; shift
  run_as agent "set -a; . \"\$HOME/.env.secrets\"; set +a; $extra python3 \"\$HOME/.hermes/skill-gate/skill_gate.py\" $*"
}

refresh_gate() { # refresh_gate <gate-args...> — owner/binding preflight without approval logging
  run_as agent "set -a; . \"\$HOME/.env.secrets\"; set +a; PYTHONPATH=\"\$HOME/.hermes/interop_runtime\" python3 \"\$HOME/.hermes/interop_runtime/automation/skill_gate_refresh.py\" $*"
}

review() { # review <review-args...> — runs skill_review.py as agent with its gate directory
  run_as agent "set -a; . \"\$HOME/.env.secrets\"; set +a; python3 \"\$HOME/.hermes/skill-gate/skill_review.py\" $*"
}

peer_attest() { # peer_attest <skill> <digest> <request-message-id> <deploy-nonce> <channel-id> [--refresh]
  local name="$1" digest="$2" message_id="$3" nonce="$4" channel="$5" refresh_arg=""
  case "${6:-}" in
    "") ;;
    --refresh) refresh_arg="--refresh" ;;
    *) die "invalid peer attestation mode" ;;
  esac
  run_as peer "$NODE_RUNTIME_ROOT_SNIPPET; RR=\$(node_runtime_root); set -a; . \"\$HOME/.env.secrets\"; set +a; exec python3 \"\$RR/automation/peer_attest.py\" --skill \"$name\" --staged-dir \"\$HOME/.hermes/skills/$name\" --hash \"$digest\" --request-message-id \"$message_id\" --deploy-nonce \"$nonce\" --channel-id \"$channel\" $refresh_arg"
}

EXECUTION_LOCK_PID=""
EXECUTION_LOCK_READ_FD=""
EXECUTION_LOCK_WRITE_FD=""

start_execution_lock() {
  local status="" rc=8
  coproc DEPLOY_EXECUTION_LEASE {
    run_as agent "$NODE_RUNTIME_ROOT_SNIPPET; RR=\$(node_runtime_root); PYTHONPATH=\"\$RR\" exec python3 \"\$RR/automation/deploy_execution_lock.py\" --skill \"$SKILL\""
  }
  EXECUTION_LOCK_PID="$DEPLOY_EXECUTION_LEASE_PID"
  EXECUTION_LOCK_READ_FD="${DEPLOY_EXECUTION_LEASE[0]}"
  EXECUTION_LOCK_WRITE_FD="${DEPLOY_EXECUTION_LEASE[1]}"
  if ! IFS= read -r status <&"$EXECUTION_LOCK_READ_FD"; then
    wait "$EXECUTION_LOCK_PID" || rc=$?
    eval "exec ${EXECUTION_LOCK_READ_FD}<&-" 2>/dev/null || true
    eval "exec ${EXECUTION_LOCK_WRITE_FD}>&-" 2>/dev/null || true
    EXECUTION_LOCK_PID="" EXECUTION_LOCK_READ_FD="" EXECUTION_LOCK_WRITE_FD=""
    die "EXECUTION-LOCK-BLOCK: another deploy is refreshing or mounting $SKILL" "$rc"
  fi
  eval "exec ${EXECUTION_LOCK_READ_FD}<&-" 2>/dev/null || true
  EXECUTION_LOCK_READ_FD=""
  [[ "$status" == "EXECUTION-LOCK-ACQUIRED skill=$SKILL" ]] \
    || die "EXECUTION-LOCK-BLOCK: invalid acquisition response"
}

release_execution_lock() {
  [[ -n "$EXECUTION_LOCK_PID" ]] || return 0
  eval "exec ${EXECUTION_LOCK_WRITE_FD}>&-" 2>/dev/null || true
  wait "$EXECUTION_LOCK_PID" || true
  EXECUTION_LOCK_PID="" EXECUTION_LOCK_WRITE_FD=""
}

check_with_attestation_refresh() {
  local digest="$1" approved=0 check_env=""
  local -a injection_args=()
  if [[ "${E2E_TEST_MODE:-}" == "1" ]]; then
    check_env="$E2E_ENV"
    injection_args=(--injection-file "\$HOME/.hermes/skill-gate/injected-approval.json")
  fi
  gate "$check_env" check --skill "$SKILL" --hash "$digest" --message-id "$MESSAGE_ID" \
    --deploy-nonce "$DEPLOY_NONCE" "${MANAGED_REQUEST_ARGS[@]}" "${injection_args[@]}" >&2 \
    || approved=$?
  if [[ "$approved" == 1 ]]; then
    approved=0
    refresh_gate --skill "$SKILL" --hash "$digest" --message-id "$MESSAGE_ID" \
      --deploy-nonce "$DEPLOY_NONCE" "${MANAGED_REQUEST_ARGS[@]}" "${injection_args[@]}" >&2 \
      || approved=$?
  fi
  if [[ "$approved" == 7 ]]; then
    peer_attest "$SKILL" "$DIGEST" "$MESSAGE_ID" "$DEPLOY_NONCE" "$DEPLOY_APPROVALS_CHANNEL_ID" --refresh >&2 \
      || die "PEER-ATTEST-BLOCK: independent peer refresh failed" 5
    approved=0
    gate "$check_env" check --skill "$SKILL" --hash "$digest" --message-id "$MESSAGE_ID" \
      --deploy-nonce "$DEPLOY_NONCE" "${MANAGED_REQUEST_ARGS[@]}" "${injection_args[@]}" >&2 \
      || approved=$?
  fi
  return "$approved"
}

sync_ops_checkout_for_peer_attest() { # fail-closed ops-checkout refresh so peer_attest runs current code
  # DG-4: when the immutable release runtime exists, converge it to origin/main by
  # installing a pinned snapshot and flipping `current`. The mutable mirror's
  # dirty/ahead state can no longer block this deploy. Until the DG-5 node flip
  # creates `current`, fall through to the historical ff-pull path unchanged.
  if run_as ops "test -e $RELEASE_CURRENT"; then
    log "converging release runtime $RELEASE_CURRENT (snapshot install + flip)"
    # Run the converger FROM the sealed release, never from the mirror whose
    # dirt we just declined to be blocked by (DG-6).
    run_as ops "bash $RELEASE_CURRENT/automation/converge-release-runtime.sh" \
      || die "SYNC-BLOCK: release snapshot install/flip failed"
    log "release runtime converged; verifier files are the sealed read-only release"
    scan_live_skill_abi
    return 0
  fi
  log "syncing ops checkout $MIRROR_CHECKOUT (ff-only) before request/attest"
  run_as ops "git -C $MIRROR_CHECKOUT rev-parse --is-inside-work-tree >/dev/null" \
    || die "SYNC-BLOCK: $MIRROR_CHECKOUT is not a git checkout"
  local dirty
  dirty="$(run_as ops "git -C $MIRROR_CHECKOUT status --porcelain")" \
    || die "SYNC-BLOCK: ops checkout status probe failed"
  [[ -z "$dirty" ]] || die "SYNC-BLOCK: ops checkout is dirty (local modifications present)"
  run_as ops "git -C $MIRROR_CHECKOUT pull --ff-only" \
    || die "SYNC-BLOCK: ff-only pull failed on ops checkout (auth/network/divergence)"
  # The peer verifier and execution lease run from this checkout. Git restores files
  # under ops's group-writable umask, so harden every executable trust-boundary input.
  run_as ops "chmod g-w,o-w $MIRROR_CHECKOUT/automation/peer_attest.py $MIRROR_CHECKOUT/automation/peer_attestation.py $MIRROR_CHECKOUT/automation/skill_review.py $MIRROR_CHECKOUT/automation/deploy_execution_lock.py $MIRROR_CHECKOUT/automation/interop/approval_lease.py" \
    || die "SYNC-BLOCK: cannot harden verifier-file permissions on ops checkout"
  local f local_hash ops_hash
  for f in peer_attest.py peer_attestation.py skill_review.py deploy_execution_lock.py interop/approval_lease.py; do
    local_hash="$(sha256sum "$REPO_ROOT/automation/$f" | cut -d' ' -f1)"
    ops_hash="$(run_as ops "cat $MIRROR_CHECKOUT/automation/$f" | sha256sum | cut -d' ' -f1)" \
      || die "SYNC-BLOCK: cannot read ops checkout automation/$f"
    [[ "$local_hash" == "$ops_hash" ]] \
      || die "SYNC-BLOCK: automation/$f differs between local repo and ops checkout (push local commit first)"
  done
  log "ops checkout in sync (verifier files hash-match local repo)"
  scan_live_skill_abi
}

# The ff-pull above just moved the shared library under every ALREADY-live skill
# snapshot. AS-3.2 proved an unrelated deploy can break three live approval flows
# at once that way. Scan the live fleet against the freshly-pulled library and WARN
# - never die: blocking here would strand the owner approval this deploy already
# consumed, a worse failure than the fail-closed refuse-to-post the skew causes.
# The checker crashing is a WARN too; a broken guard must not break a deploy.
# DEPLOY_ABI_STRICT=1 escalates to a block once the false-positive rate is known.
scan_live_skill_abi() {
  local out rc=0
  # Resolve the runtime root here so the function is self-contained (the isolated
  # scan harness does not set the script global); default to the configured mirror.
  local runtime_root="${RUNTIME_ROOT:-${MIRROR_CHECKOUT:-}}"
  out="$(run_as ops "python3 -I $runtime_root/automation/skill_library_abi.py ${STORE_ROOT}/live $runtime_root/automation" 2>&1)" || rc=$?
  if (( rc == 0 )); then
    return 0
  fi
  log "MOUNT-ABI-WARN: a live skill can no longer call the pulled shared library"
  while IFS= read -r line; do [[ -n "$line" ]] && log "MOUNT-ABI-WARN: ${line}"; done <<< "$out"
  if [[ "${DEPLOY_ABI_STRICT:-}" == "1" ]]; then
    die "MOUNT-ABI-BLOCK: DEPLOY_ABI_STRICT=1 and a live skill has an ABI break" 4
  fi
  return 0
}

cleanup_e2e_injection() {
  [[ "${E2E_TEST_MODE:-}" == "1" ]] || return 0
  run_as agent "rm -f \"\$HOME/.hermes/skill-gate/e2e.secret\" \"\$HOME/.hermes/skill-gate/injected-approval.json\"" || true
}

cleanup_managed_provenance() {
  [[ -n "$MANAGED_PROVENANCE_FILE" ]] && rm -f "$MANAGED_PROVENANCE_FILE"
  [[ -n "$MANAGED_PROVENANCE_REMOTE" ]] || return 0
  run_as agent "rm -f \"$MANAGED_PROVENANCE_REMOTE\"" || true
}

cleanup_deploy_temps() {
  release_execution_lock
  cleanup_e2e_injection
  cleanup_managed_provenance
}

trap cleanup_deploy_temps EXIT

# ---------- argument parsing ----------
SKILL="${1:-}"; shift || true
[[ -n "$SKILL" ]] || die "usage: deploy-skill.sh <skill> [--request-only|--approve-only|--fresh|--sandbox-only|--remove|--activate-managed <quarantine-dir>]"
[[ "$SKILL" =~ ^[a-z0-9][a-z0-9-]{1,40}$ ]] || die "invalid skill name: $SKILL"
REQUEST_ONLY=0 APPROVE_ONLY=0 FRESH=0 SANDBOX_ONLY=0 REMOVE=0
ACTIVATE_MANAGED=0
QUARANTINE_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --request-only) REQUEST_ONLY=1 ;;
    --approve-only) APPROVE_ONLY=1 ;;
    --fresh) FRESH=1 ;;
    --sandbox-only) SANDBOX_ONLY=1 ;;
    --remove) REMOVE=1 ;;
    --activate-managed)
      [[ $# -ge 2 ]] || die "--activate-managed requires a quarantine directory"
      ACTIVATE_MANAGED=1
      QUARANTINE_DIR="$2"
      shift 2
      continue
      ;;
    *) die "unknown flag: $1" ;;
  esac
  shift
done

if [[ "$REMOVE" == 1 ]]; then
  remove_live_skill "$SKILL" || die "privileged skill removal failed"
  run_as peer "rm -rf \"\$HOME/.hermes/skills/$SKILL\""
  for acct in agent peer; do
    if hermes_lists_skill "$acct" "$SKILL"; then die "removal failed: $SKILL still listed on $acct"; fi
    log "REMOVED $SKILL from $acct (hermes skills list: absent)"
  done
  exit 0
fi

if [[ "$ACTIVATE_MANAGED" == 0 && "$APPROVE_ONLY" == 0 && "$SANDBOX_ONLY" == 0 && "$REQUEST_ONLY" == 0 && "$SKILL" == managed-* ]]; then
  die "MANAGED-BLOCK: mounting a managed skill requires --activate-managed"
fi

if [[ "$ACTIVATE_MANAGED" == 1 ]]; then
  [[ "$SKILL" == managed-* ]] || die "MANAGED-BLOCK: --activate-managed requires a managed-* skill name"
  MANAGED_BASE="${SKILL#managed-}"
  if readlink "$STORE_ROOT/live/$MANAGED_BASE" >/dev/null; then
    die "COLLISION-BLOCK: managed skill $SKILL conflicts with live base $MANAGED_BASE; remove one with --remove"
  fi
else
  if readlink "$STORE_ROOT/live/managed-$SKILL" >/dev/null; then
    die "COLLISION-BLOCK: base skill $SKILL conflicts with live managed-$SKILL; remove one with --remove"
  fi
fi

SRC_DIR="${SKILL_SRC_DIR:-$REPO_ROOT/skills/$SKILL}"
MANAGED_PUBLISHER=""
MANAGED_REQUEST_ARGS=()
if [[ "$ACTIVATE_MANAGED" == 1 ]]; then
  [[ -d "$QUARANTINE_DIR" ]] || die "MANAGED-BLOCK: quarantine directory missing: $QUARANTINE_DIR"
  MANAGED_SKILL_DIR="$QUARANTINE_DIR/$SKILL"
  [[ -f "$QUARANTINE_DIR/manifest.json" && -f "$QUARANTINE_DIR/provenance.json" && -f "$MANAGED_SKILL_DIR/SKILL.md" ]] \
    || die "MANAGED-BLOCK: quarantine layout requires manifest.json, provenance.json, and $SKILL/SKILL.md"
  MANAGED_FIELDS="$(PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" python3 -c 'from pathlib import Path; from automation.managed_skills.manifest import manifest_digest, parse_manifest; import json, sys; quarantine = Path(sys.argv[1]); manifest = parse_manifest((quarantine / "manifest.json").read_text(encoding="utf-8")); provenance = json.loads((quarantine / "provenance.json").read_text(encoding="utf-8")); valid = isinstance(provenance, dict) and provenance.get("publisher") == manifest.publisher and provenance.get("sequence") == manifest.release_sequence and provenance.get("tag") == f"{manifest.skill}/v{manifest.release_sequence}"; valid or sys.exit(1); print(manifest.publisher, manifest.skill, manifest.skill_sha256, manifest.release_sequence, provenance["tag"], manifest_digest(manifest), sep="\n")' "$QUARANTINE_DIR")" \
    || die "MANAGED-BLOCK: quarantine manifest/provenance is invalid"
  mapfile -t MANAGED_FIELDS <<<"$MANAGED_FIELDS"
  [[ "${#MANAGED_FIELDS[@]}" == 6 ]] || die "MANAGED-BLOCK: quarantine manifest fields are incomplete"
  MANAGED_PUBLISHER="${MANAGED_FIELDS[0]}"
  MANAGED_SKILL="${MANAGED_FIELDS[1]}"
  MANAGED_DIGEST="${MANAGED_FIELDS[2]}"
  MANAGED_SEQUENCE="${MANAGED_FIELDS[3]}"
  MANAGED_TAG="${MANAGED_FIELDS[4]}"
  MANAGED_MANIFEST_SHA256="${MANAGED_FIELDS[5]}"
  [[ "$MANAGED_SKILL" == "$SKILL" ]] || die "MANAGED-BLOCK: manifest skill does not match requested skill"
  QUARANTINE_DIGEST="$(skill_digest "$MANAGED_SKILL_DIR")"
  [[ "$QUARANTINE_DIGEST" == "$MANAGED_DIGEST" ]] || die "MANAGED-BLOCK: quarantine skill digest does not match manifest"
  SRC_DIR="$MANAGED_SKILL_DIR"
  DIGEST="$MANAGED_DIGEST"
  MANAGED_PROVENANCE_FILE="$(mktemp)" || die "MANAGED-BLOCK: cannot create provenance file"
  python3 -c 'import json, sys; print(json.dumps({"publisher": sys.argv[1], "tag": sys.argv[2], "release_sequence": int(sys.argv[3]), "manifest_sha256": sys.argv[4]}, sort_keys=True, separators=(",", ":")))' \
    "$MANAGED_PUBLISHER" "$MANAGED_TAG" "$MANAGED_SEQUENCE" "$MANAGED_MANIFEST_SHA256" > "$MANAGED_PROVENANCE_FILE" \
    || die "MANAGED-BLOCK: cannot render provenance file"
else
  [[ -f "$SRC_DIR/SKILL.md" ]] || die "skill source missing: $SRC_DIR/SKILL.md"
  DIGEST="$(skill_digest "$SRC_DIR")"
fi
log "skill=$SKILL sha256=$DIGEST"

# Deploy guard: a mounted skill must already exist in origin/main, or the next clean
# deploy from any other session silently reverts it. Sandbox-only runs, managed
# quarantine dirs and explicit SKILL_SRC_DIR overrides are exempt by design — they are
# deliberately not repository state.
if [[ "$ACTIVATE_MANAGED" == 0 && "$SANDBOX_ONLY" == 0 && -z "${SKILL_SRC_DIR:-}" ]]; then
  source "$REPO_ROOT/automation/deploy_provenance.sh"
  deploy_provenance_check "$REPO_ROOT" "$SRC_DIR" || exit 4
fi

# ---------- stage 1: sandbox on peer with DUMMY secrets ----------
sandbox_block() { run_as peer "rm -rf \"\$HOME/.hermes/skills/$SKILL\"" || true; die "SANDBOX-BLOCK: $1" 2; }

log "stage 1/4 SANDBOX (peer, dummy secrets)"
sync_ops_checkout_for_peer_attest
start_execution_lock
push_skill peer "$SRC_DIR" "$SKILL"

# Modules the staged gate imports at runtime. skill_gate.py imports the shared
# approval lifecycle (approval_lifecycle → approval_lease) plus its skill-gate
# adapter (skill_gate_specs → skill_gate_approval → skill_gate_request) — stage
# every one or the staged gate raises ImportError on the node and EVERY deploy
# fails closed, including the deploy that would ship the fix. automation/ and
# automation/interop/ resolve as PEP 420 namespace packages on the node, so no
# __init__.py needs staging.
GATE_HELPERS=(skill_gate.py skill_gate_refresh.py skill_gate_review.py
              peer_attestation.py skill_gate_e2e.py
              skill_gate_specs.py skill_gate_approval.py skill_gate_request.py
              skill_gate_retire.py skill_gate_surface.py)
GATE_INTEROP_HELPERS=(interop/approval_lease.py interop/approval_lifecycle.py
                      interop/approval_surface.py interop/approval_directory.py
                      interop/injection_adapter.py)

# Preflight: fail before the first byte is copied, so a renamed or missing
# module can never leave a half-staged (import-broken) gate on the node.
for src in skill_gate.py "${GATE_HELPERS[@]}" "${GATE_INTEROP_HELPERS[@]}"; do
  [[ -f "$REPO_ROOT/automation/$src" ]] \
    || die "STAGE-BLOCK: gate module missing from checkout: automation/$src"
done

# Runtime-Python (3.11) parse gate: hermes runs no_agent cron scripts under its
# uv-managed CPython (observed 3.11.15), NOT the dev/interactive python3 (3.12). PEP 701
# f-strings and PEP 695 `type` aliases parse clean on 3.12 yet SyntaxError at import on
# 3.11, silently killing watchers (incident t_90a2e810: triage_gate.py broke the mail
# approval watcher). The peer runs the same hermes runtime, so parse every module the
# skill ships under that exact interpreter before the 3.12 scenario below can pass it.
# Dev-time twin scan: tests/unit/test_py311_syntax_guard.py.
RUNTIME_PARSE="$(run_as peer "\"\$HOME/.hermes/hermes-agent/venv/bin/python\" - \"\$HOME/.hermes/skills/$SKILL\" <<'PY'
import pathlib, sys
root = pathlib.Path(sys.argv[1])
failures = []
for path in sorted(root.rglob(\"*.py\")):
    if \"__pycache__\" in path.parts:
        continue
    try:
        compile(path.read_text(encoding=\"utf-8\"), str(path), \"exec\")
    except SyntaxError as error:
        failures.append(f\"{path.name}:{error.lineno}: {error.msg}\")
if failures:
    print(\"RUNTIME-PARSE-FAIL \" + \"; \".join(failures))
    sys.exit(1)
print(\"RUNTIME-PARSE-PASS python\" + \".\".join(map(str, sys.version_info[:3])))
PY
")" || sandbox_block "skill does not parse under the hermes runtime interpreter (py3.11); 3.12-only syntax? ${RUNTIME_PARSE:-runtime python missing on peer} (see tests/unit/test_py311_syntax_guard.py)"
log "runtime parse (peer): $(tail -n1 <<<"$RUNTIME_PARSE")"

run_as peer "python3 - \"\$HOME/.hermes/skills/$SKILL/SKILL.md\" \"$SKILL\" <<'PY'
import sys, pathlib
text = pathlib.Path(sys.argv[1]).read_text(encoding=\"utf-8\")
parts = text.split(\"---\n\")
assert text.startswith(\"---\n\") and len(parts) >= 3, \"missing frontmatter\"
fields = {}
for line in parts[1].splitlines():
    if \":\" in line and not line.startswith((\" \", \"\t\")):
        key, value = line.split(\":\", 1)
        fields[key.strip()] = value.strip().strip('\"')
assert fields.get(\"name\") == sys.argv[2], f\"frontmatter name != {sys.argv[2]}\"
assert len(fields.get(\"description\", \"\")) >= 10, \"description missing/too short\"
print(\"LINT-PASS name+description ok\")
PY" || sandbox_block "SKILL.md frontmatter lint failed"

hermes_lists_skill peer "$SKILL" || sandbox_block "hermes skills list does not show $SKILL on peer"
log "hermes discovery on peer: OK"

run_as peer "test -x \"\$HOME/.hermes/skills/$SKILL/scripts/scenario.sh\" || chmod +x \"\$HOME/.hermes/skills/$SKILL/scripts/scenario.sh\" 2>/dev/null; test -f \"\$HOME/.hermes/skills/$SKILL/scripts/scenario.sh\"" \
  || sandbox_block "skill ships no scripts/scenario.sh (sandbox scenario is mandatory)"

# The scenario reaches shared repo modules through AUTOPHAGY_REPO_ROOT, and different
# skills default it differently (mail resolves it skill-relative, calendar defaults to
# the ops checkout for its peer registry). Pin it to the resolved runtime root
# (release `current`, else the mirror), resolved NODE-SIDE — one root, no staged
# duplicate to drift.
SCENARIO_OUT="$(run_as peer "$NODE_RUNTIME_ROOT_SNIPPET; RR=\$(node_runtime_root); env -i HOME=\"\$HOME\" PATH=/usr/bin:/bin AUTOPHAGY_REPO_ROOT=\"\$RR\" AUTOPHAGY_DEMO_SECRET=\"DUMMY-w18-sandbox-\$(date +%s)\" bash \"\$HOME/.hermes/skills/$SKILL/scripts/scenario.sh\"")" \
  || sandbox_block "scenario failed under dummy secrets"
grep -q "SCENARIO-PASS" <<<"$SCENARIO_OUT" || sandbox_block "scenario output missing SCENARIO-PASS marker"
log "scenario: $(tail -n1 <<<"$SCENARIO_OUT")"

run_as peer "if [ -r /home/agent/.env.secrets ]; then echo ISOLATION-FAIL; exit 1; else echo 'ISOLATION-OK peer cannot read agent secrets'; fi" \
  || sandbox_block "isolation probe failed: peer could read agent secrets"
log "sandbox PASS (lint + discovery + dummy-secret scenario + isolation)"
[[ "$SANDBOX_ONLY" == 1 ]] && { run_as peer "rm -rf \"\$HOME/.hermes/skills/$SKILL\""; exit 0; }

# ---------- stage 2: deterministic, hash-bound review on agent ----------
log "stage 2/4 REVIEW (agent, deterministic hash-bound verdict)"
run_as agent "umask 077; mkdir -p \"\$HOME/.hermes/skill-gate\" && cat > \"\$HOME/.hermes/skill-gate/skill_review.py\"" \
  < "$REPO_ROOT/automation/skill_review.py" || die "REVIEW-BLOCK: review tool staging failed" 5
run_as agent "chmod 600 \"\$HOME/.hermes/skill-gate/skill_review.py\"" || die "REVIEW-BLOCK: review tool permissions failed" 5
stage_review_source "$SRC_DIR" "$SKILL" "$DIGEST" || { cleanup_review_staging "$SKILL"; die "REVIEW-BLOCK: review source staging failed" 5; }
save_review_scenario "$SCENARIO_OUT" "$SKILL" "$DIGEST" || { cleanup_review_staging "$SKILL"; die "REVIEW-BLOCK: sandbox scenario evidence staging failed" 5; }
REVIEWED=0
review review --skill "$SKILL" --skill-dir "\$HOME/.hermes/skill-gate/review-staging/$SKILL/$DIGEST/$SKILL" \
  --hash "$DIGEST" --scenario-output-file "\$HOME/.hermes/skill-gate/review-staging/$SKILL/$DIGEST/scenario.out" >&2 || REVIEWED=$?
if [[ "$REVIEWED" != 0 ]]; then
  run_as peer "rm -rf \"\$HOME/.hermes/skills/$SKILL\"" || true
  cleanup_review_staging "$SKILL"
  die "REVIEW-BLOCK: deterministic security review failed" 5
fi
log "review PASS (recorded hash-bound verdict)"

# ---------- stage 3: request, independent peer attestation, and owner approval (preceded by ops-checkout ff-only sync) ----------
log "stage 3/4 REQUEST + PEER-ATTEST + APPROVAL (#approvals)"
# Resolve the shared-guild deploy approvals channel once (fail-open to empty:
# "" -> peer_attest --channel-id "" -> None -> guild-scan fallback).
DEPLOY_APPROVALS_CHANNEL_ID="$(run_as agent "python3 -c 'import json,pathlib; print(json.loads(pathlib.Path(\"~/.hermes/interop/config.json\").expanduser().read_text()).get(\"deploy_approvals_channel_id\") or \"\")'" 2>/dev/null || true)"

run_as agent "umask 077; mkdir -p \"\$HOME/.hermes/skill-gate\" && cat > \"\$HOME/.hermes/skill-gate/skill_gate.py\"" \
  < "$REPO_ROOT/automation/skill_gate.py"
for helper in "${GATE_HELPERS[@]}"; do
  run_as agent "umask 077; mkdir -p \"\$HOME/.hermes/interop_runtime/automation\" && cat > \"\$HOME/.hermes/interop_runtime/automation/$helper\"" \
    < "$REPO_ROOT/automation/$helper"
done
for helper in "${GATE_INTEROP_HELPERS[@]}"; do
  run_as agent "umask 077; mkdir -p \"\$HOME/.hermes/interop_runtime/automation/interop\" && cat > \"\$HOME/.hermes/interop_runtime/automation/$helper\"" \
    < "$REPO_ROOT/automation/$helper"
done
GATE_STAGED_PATHS="\"\$HOME/.hermes/skill-gate/skill_gate.py\""
for helper in "${GATE_HELPERS[@]}" "${GATE_INTEROP_HELPERS[@]}"; do
  GATE_STAGED_PATHS+=" \"\$HOME/.hermes/interop_runtime/automation/$helper\""
done
run_as agent "chmod 600 $GATE_STAGED_PATHS"

if [[ "$ACTIVATE_MANAGED" == 1 ]]; then
  MANAGED_PROVENANCE_REMOTE="\$HOME/.hermes/skill-gate/managed-provenance-$SKILL-$DIGEST.json"
  run_as agent "umask 077; cat > \"$MANAGED_PROVENANCE_REMOTE\"" < "$MANAGED_PROVENANCE_FILE" \
    || die "MANAGED-BLOCK: provenance staging failed"
  MANAGED_REQUEST_ARGS=(--provenance-file "$MANAGED_PROVENANCE_REMOTE")
fi

if [[ -n "${APPROVAL_MESSAGE_ID:-}" ]]; then
  MESSAGE_ID="$APPROVAL_MESSAGE_ID"
  DEPLOY_NONCE="${DEPLOY_NONCE:-}"
  [[ "$DEPLOY_NONCE" =~ ^[0-9a-f]{32}$ ]] || die "APPROVAL_MESSAGE_ID requires a valid DEPLOY_NONCE"
else
  FRESH_FLAG=""; [[ "$FRESH" == 1 ]] && FRESH_FLAG="--fresh"
  REQUEST_JSON="$(gate "SKILL_PROPOSAL_SOURCE='${SKILL_PROPOSAL_SOURCE:-manual}'" \
    request --skill "$SKILL" --hash "$DIGEST" --json $FRESH_FLAG "${MANAGED_REQUEST_ARGS[@]}")" || { rc=$?; [[ $rc == 3 ]] && die "weekly auto-proposal rate limit" 3; [[ $rc == 6 ]] && die "approval lifecycle refusal (existing live request preserved; gate stderr carries reason=)" 6; die "approval request failed"; }
  mapfile -t REQUEST_FIELDS < <(python3 -c 'import json, sys; row = json.load(sys.stdin); print(row["message_id"]); print(row["deploy_nonce"])' <<<"$REQUEST_JSON")
  [[ "${#REQUEST_FIELDS[@]}" == 2 ]] || die "approval request did not return message id and deploy nonce"
  MESSAGE_ID="${REQUEST_FIELDS[0]}"
  DEPLOY_NONCE="${REQUEST_FIELDS[1]}"
fi
log "approval request posted; peer attestation required"
PEER_ATTESTED=0
peer_attest "$SKILL" "$DIGEST" "$MESSAGE_ID" "$DEPLOY_NONCE" "$DEPLOY_APPROVALS_CHANNEL_ID" >&2 || PEER_ATTESTED=$?
if [[ "$PEER_ATTESTED" != 0 ]]; then
  run_as peer "rm -rf \"\$HOME/.hermes/skills/$SKILL\"" || true
  cleanup_review_staging "$SKILL"
  die "PEER-ATTEST-BLOCK: independent peer review failed" 5
fi
log "peer attestation PASS (posted by peer bot)"
[[ "$REQUEST_ONLY" == 1 ]] && { run_as peer "rm -rf \"\$HOME/.hermes/skills/$SKILL\"" || true; cleanup_review_staging "$SKILL"; log "request-only mode: attested but not mounting"; echo "$MESSAGE_ID"; exit 0; }

if [[ "${E2E_TEST_MODE:-}" == "1" ]]; then
  log "E2E regression path: signed injected approval (production gateway refuses this mode)"
  run_as agent "umask 077; openssl rand -hex 32 > \"\$HOME/.hermes/skill-gate/e2e.secret\""
  E2E_ENV='E2E_TEST_MODE=1 INTEROP_E2E_SECRET=$(cat "$HOME/.hermes/skill-gate/e2e.secret")'
  gate "$E2E_ENV" sign --skill "$SKILL" --hash "$DIGEST" --message-id "$MESSAGE_ID" \
    --out "\$HOME/.hermes/skill-gate/injected-approval.json" >&2
fi
APPROVED=0
check_with_attestation_refresh "$DIGEST" || APPROVED=$?

if [[ "$APPROVED" != 0 ]]; then
  run_as peer "rm -rf \"\$HOME/.hermes/skills/$SKILL\"" || true
  cleanup_review_staging "$SKILL"
  cleanup_e2e_injection
  log "approval ABSENT or INVALID — NOT mounting (message $MESSAGE_ID stays pending for the owner)"
  exit 1
fi
log "approval GRANTED (logged to approvals.jsonl)"

if [[ "$APPROVE_ONLY" == 1 ]]; then
  run_as peer "rm -rf \"\$HOME/.hermes/skills/$SKILL\"" || true
  cleanup_review_staging "$SKILL"
  cleanup_e2e_injection
  printf '%s:%s\n' "$MESSAGE_ID" "$DEPLOY_NONCE"
  exit 0
fi

# ---------- stage 4: recheck reviewed current hash, then mount its artifact ----------
CURRENT_DIGEST="$(skill_digest "$SRC_DIR")"
if [[ "$CURRENT_DIGEST" != "$DIGEST" ]]; then
  run_as peer "rm -rf \"\$HOME/.hermes/skills/$SKILL\"" || true
  cleanup_review_staging "$SKILL"
  die "REVIEW-BLOCK: source changed after review" 5
fi
REVIEW_CURRENT=0
review check --skill "$SKILL" --hash "$CURRENT_DIGEST" >&2 || REVIEW_CURRENT=$?
if [[ "$REVIEW_CURRENT" != 0 ]]; then
  run_as peer "rm -rf \"\$HOME/.hermes/skills/$SKILL\"" || true
  cleanup_review_staging "$SKILL"
  die "REVIEW-BLOCK: PASS verdict missing for current skill hash" 5
fi
MOUNT_APPROVED=0
check_with_attestation_refresh "$CURRENT_DIGEST" || MOUNT_APPROVED=$?
if [[ "$MOUNT_APPROVED" != 0 ]]; then
  run_as peer "rm -rf \"\$HOME/.hermes/skills/$SKILL\"" || true
  cleanup_review_staging "$SKILL"
  cleanup_e2e_injection
  die "MOUNT-BLOCK: owner approval or peer attestation no longer valid" 1
fi
log "stage 4/4 MOUNT (root-owned immutable skill store)"
if [[ "$ACTIVATE_MANAGED" == 1 ]]; then
  install_managed_skill "$SRC_DIR" "$MANAGED_PUBLISHER" "$SKILL" "$DIGEST" || die "MANAGED-BLOCK: privileged managed artifact install failed" 5
else
  install_reviewed_skill "$SRC_DIR" "$SKILL" "$DIGEST" || die "REVIEW-BLOCK: privileged reviewed artifact install failed" 5
fi
hermes_lists_skill agent "$SKILL" || die "mounted but hermes skills list does not show $SKILL on agent"
INVOKE_OUT="$(run_as agent "env -i HOME=\"\$HOME\" PATH=/usr/bin:/bin AUTOPHAGY_DEMO_SECRET=DUMMY-w18-agent-invoke bash \"\$HOME/.hermes/skills/$SKILL/scripts/scenario.sh\"")" \
  || die "post-mount invoke smoke failed on agent"
log "invoke: $(head -n1 <<<"$INVOKE_OUT")"
# The MOUNT consumed the owner's decision; retire its pending record so the NEXT
# deploy of this skill is not blocked by a request the lifecycle guard (correctly)
# refuses to destroy. Compare-and-swap inside the gate: a record that no longer
# binds this (skill, hash, message id) is left alone. A failure here is LOUD but
# NEVER fatal — the reviewed artifact is already live, so rolling the mount back
# over leftover bookkeeping would be the worse outcome.
CONSUMED=0
gate "" consume --skill "$SKILL" --hash "$DIGEST" --message-id "$MESSAGE_ID" >&2 || CONSUMED=$?
[[ "$CONSUMED" == 0 ]] || log "CONSUME-WARN: pending approval record NOT retired for $SKILL (rc=$CONSUMED); mount stands. Retire it with: skill_gate.py abandon --skill $SKILL --hash $DIGEST --message-id $MESSAGE_ID --reason <text>"
release_execution_lock
run_as peer "rm -rf \"\$HOME/.hermes/skills/$SKILL\"" || true
cleanup_review_staging "$SKILL"
cleanup_e2e_injection
log "DEPLOYED $SKILL (sandbox→review→approval→mount complete; sandbox copy cleaned)"
exit 0
