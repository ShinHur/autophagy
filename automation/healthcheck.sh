#!/usr/bin/env bash
# Read-only liveness monitor for the deployed autophagy services.
#
# Run as the configured operator. HEALTHCHECK_SSH_USER and HEALTHCHECK_SSH_IDENTITY
# key is readable). It deliberately uses SSH plus read-only GET and systemctl
# --user is-active probes, so it remains independent of Hermes.
set -euo pipefail

# The deploy-checkout drift verdict + its recovery text live in a sibling library
# so this file stays under the 250 pure-LOC gate. It runs LOCALLY (no ssh/sudo).
# shellcheck source=automation/checkout_mirror_probe.sh
source "$(dirname "${BASH_SOURCE[0]}")/checkout_mirror_probe.sh"

: "${HEALTHCHECK_LOG_DIR:?HEALTHCHECK_LOG_DIR is required — see .env.example}"
: "${HEALTHCHECK_HOST_A:?HEALTHCHECK_HOST_A is required — see .env.example}"
: "${HEALTHCHECK_HOST_B:?HEALTHCHECK_HOST_B is required — see .env.example}"
: "${HEALTHCHECK_SSH_USER:?HEALTHCHECK_SSH_USER is required — see .env.example}"
: "${HEALTHCHECK_DASHBOARD_AUTH_URL:?HEALTHCHECK_DASHBOARD_AUTH_URL is required — see .env.example}"
: "${HEALTHCHECK_OPS_CHECKOUT:?HEALTHCHECK_OPS_CHECKOUT is required — see .env.example}"
: "${HEALTHCHECK_REPAIR_CLI:?HEALTHCHECK_REPAIR_CLI is required — see .env.example}"
: "${HEALTHCHECK_MCP_COLLECTION:?HEALTHCHECK_MCP_COLLECTION is required — see .env.example}"
: "${HEALTHCHECK_REPAIR_ACCOUNT:?HEALTHCHECK_REPAIR_ACCOUNT is required — see .env.example}"
readonly LOG_DIR="$HEALTHCHECK_LOG_DIR"
readonly HOST_A="$HEALTHCHECK_HOST_A"
readonly HOST_B="$HEALTHCHECK_HOST_B"
readonly REPAIR_ACCOUNT="$HEALTHCHECK_REPAIR_ACCOUNT"
readonly SERVICE_UNIT="hermes-gateway.service"
if [[ -v HEALTHCHECK_SSH_IDENTITY ]]; then
  readonly SSH_IDENTITY="$HEALTHCHECK_SSH_IDENTITY"
elif [[ -r "$HOME/.ssh/autophagy-healthcheck" ]]; then
  readonly SSH_IDENTITY="$HOME/.ssh/autophagy-healthcheck"
else
  readonly SSH_IDENTITY=""
fi
readonly SSH_REMOTE_USER="$HEALTHCHECK_SSH_USER"
SSH_OPTIONS=(
  -o BatchMode=yes
  -o ClearAllForwardings=yes
  -o ConnectTimeout=15
  -o StrictHostKeyChecking=yes
)
if [[ -n "$SSH_IDENTITY" ]]; then
  SSH_OPTIONS+=(-o IdentitiesOnly=yes -i "$SSH_IDENTITY")
fi
readonly -a SSH_OPTIONS

# Add an ordinary deployed service by adding one line here. Fields are:
# display name | probe type | node | account | target
readonly -a LIVE_CHECKS=(
  "host-a LiteLLM|http_200|${HOST_A}|ops|http://127.0.0.1:4000/health/liveliness"
  "host-a agent ${SERVICE_UNIT}|user_unit_active|${HOST_A}|agent|${SERVICE_UNIT}"
  "host-a peer ${SERVICE_UNIT}|user_unit_active|${HOST_A}|peer|${SERVICE_UNIT}"
  "host-b embedding|embedding_health|${HOST_B}|ops|http://127.0.0.1:8001/health"
  "host-b Qdrant|qdrant_health|${HOST_B}|ops|http://127.0.0.1:6333/healthz"
  "host-b MCP|mcp_health|${HOST_B}|ops|http://127.0.0.1:8765/health"
  "host-a report-hub collector|user_unit_active|${HOST_A}|ops|report-hub-collector.service"
  "host-a report-hub dashboard|user_unit_active|${HOST_A}|ops|report-hub-dashboard.service"
  "host-a report-hub dashboard auth|http_unauth_401|${HOST_A}|ops|${HEALTHCHECK_DASHBOARD_AUTH_URL}"
  "host-a ops checkout mirrors origin/main|checkout_mirrors_origin|${HOST_A}|ops|${HEALTHCHECK_OPS_CHECKOUT}"
)

log() {
  printf '[healthcheck] %s\n' "$*"
}

usage() {
  cat >&2 <<'EOF'
Usage: healthcheck.sh [--synthetic-failure]

Without arguments, check the deployed services. --synthetic-failure performs
one read-only is-active probe for a deliberately nonexistent ops user unit; it
exists only to prove failure reporting without disrupting a real service.
EOF
  exit 2
}

require_commands() {
  local command_name
  for command_name in "$@"; do
    command -v "$command_name" >/dev/null 2>&1 || {
      printf '[healthcheck] ERROR: required command not found: %s\n' "$command_name" >&2
      exit 1
    }
  done
}

setup_log() {
  local timestamp

  umask 077
  mkdir -p -m 700 -- "$LOG_DIR"
  chmod 700 -- "$LOG_DIR"
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  LOG_FILE="${LOG_DIR}/healthcheck-${timestamp}.log"
  : > "$LOG_FILE"
  chmod 600 -- "$LOG_FILE"
  exec > >(tee -a "$LOG_FILE") 2>&1
  log "log=${LOG_FILE}"
}

# A repair ticket carries the check name, which is all an operator needs when the
# remedy is obvious (restart, re-auth). Deploy-checkout drift is the case where
# it is not: the commits stranded in the checkout exist nowhere else, so the
# reflexive repair - discard and realign - destroys them. Probe types without a
# rule here ship the name alone.
repair_guidance() {
  case "$1" in
    checkout_mirrors_origin)
      checkout_mirror_guidance "$HEALTHCHECK_OPS_CHECKOUT"
      ;;
    *) ;;
  esac
}

report_repair() {
  local check_name="$1"
  local probe_type="$2"
  local ssh_target="$HOST_A" output command_status=0

  [[ "$check_name" =~ ^[a-zA-Z0-9_.@:/[:space:]-]+$ ]] || return 1
  valid_account "$REPAIR_ACCOUNT" || return 1
  [[ -z "$SSH_REMOTE_USER" ]] || ssh_target="${SSH_REMOTE_USER}@${HOST_A}"
  output="$( { printf 'healthcheck failure: %s\n' "$check_name"; repair_guidance "$probe_type"; } | timeout 90 ssh "${SSH_OPTIONS[@]}" "$ssh_target" "sudo -n -u ${REPAIR_ACCOUNT} -H python3 -I $HEALTHCHECK_REPAIR_CLI detect --source healthcheck --location '$check_name' --stdin" 2>&1)" || command_status=$?
  if (( command_status == 0 )); then
    log "REPAIR_TICKET ${output}"
  else
    log "REPAIR_TICKET_FAILED rc=${command_status}"
  fi
}

# Capture only a probe's response for validation. No response body is printed
# or logged, so logs contain only check names and up/down state.
capture_on_node() {
  local node="$1"
  local remote_command="$2"
  local result ssh_target="$node" command_status=0

  [[ -z "$SSH_REMOTE_USER" ]] || ssh_target="${SSH_REMOTE_USER}@${node}"
  result="$(timeout 45 ssh "${SSH_OPTIONS[@]}" "$ssh_target" "$remote_command" 2>&1)" || command_status=$?
  result="$(printf '%s\n' "$result" | grep -v 18789 || true)"

  (( command_status == 0 )) || return "$command_status"
  printf '%s' "$result"
}

valid_account() {
  [[ "$1" =~ ^[a-z_][a-z0-9_-]*$ ]]
}

valid_http_url() {
  local pattern='^https?://[a-zA-Z0-9._:-]+/[a-zA-Z0-9._~:/?&=%+-]*$'
  [[ "$1" =~ $pattern ]]
}

valid_unit() {
  [[ "$1" =~ ^[a-zA-Z0-9_.@-]+$ ]]
}

valid_abs_path() {
  [[ "$1" =~ ^/[A-Za-z0-9._/-]*$ ]]
}

probe_http_200() {
  local node="$1"
  local account="$2"
  local url="$3"
  local status

  valid_account "$account" && valid_http_url "$url" || return 1
  status="$(capture_on_node "$node" "sudo -n -u ${account} -H curl --fail --silent --output /dev/null --write-out '%{http_code}' '${url}'")" || return 1
  [[ "$status" == "200" ]]
}

probe_user_unit_active() {
  local node="$1"
  local account="$2"
  local unit="$3"
  local status

  valid_account "$account" && valid_unit "$unit" || return 1
  status="$(capture_on_node "$node" "sudo -n -u ${account} -H XDG_RUNTIME_DIR=/run/user/\$(id -u ${account}) systemctl --user is-active ${unit}")" || return 1
  [[ "$status" == "active" ]]
}

# The W3-4 dashboard must both respond and refuse unauthenticated access, so
# the healthy result for a credential-free probe is exactly HTTP 401.
probe_http_unauth_401() {
  local node="$1"
  local account="$2"
  local url="$3"
  local status

  valid_account "$account" && valid_http_url "$url" || return 1
  status="$(capture_on_node "$node" "sudo -n -u ${account} -H curl --silent --output /dev/null --write-out '%{http_code}' '${url}'")" || return 1
  [[ "$status" == "401" ]]
}

# The following three probes use exactly the W2-1 integration commands and
# validate their documented healthy results without printing response bodies.
probe_embedding_health() {
  local node="$1"
  local account="$2"
  local url="$3"
  local response

  valid_account "$account" && valid_http_url "$url" || return 1
  response="$(capture_on_node "$node" "sudo -n -u ${account} -H curl --fail --silent '${url}'")" || return 1
  [[ "$response" == *'"status"'*'"ok"'* && "$response" == *'"model"'*'"BAAI/bge-m3"'* && "$response" == *'"dimensions"'*1024* ]]
}

probe_qdrant_health() {
  local node="$1"
  local account="$2"
  local url="$3"
  local response

  valid_account "$account" && valid_http_url "$url" || return 1
  response="$(capture_on_node "$node" "sudo -n -u ${account} -H curl --fail --silent '${url}'")" || return 1
  [[ "$response" == "healthz check passed" ]]
}

probe_mcp_health() {
  local node="$1"
  local account="$2"
  local url="$3"
  local response

  valid_account "$account" && valid_http_url "$url" || return 1
  response="$(capture_on_node "$node" "sudo -n -u ${account} -H curl --fail --silent '${url}'")" || return 1
  [[ "$response" == *'"status"'*'"ok"'* && "$response" == *'"collection"'*"\"${HEALTHCHECK_MCP_COLLECTION}\""* ]]
}

# The deploy checkout is a one-way mirror of origin/main. This probe runs LOCALLY:
# healthcheck runs as ops ON host-a and the checkout is a local path there, so it
# needs neither ssh (allowlist-denied) nor sudo (sudoers-denied) - both rc=126. The
# verdict (clean/dirty/ahead/behind/unknown-remote) lives in checkout_mirror_probe.sh.
# Read-only: it uses git ls-remote (no local ref written), never fetch/pull/reset.
# An unreachable origin degrades to a PASS + BEHIND-UNKNOWN, never a cry-wolf fail.
probe_checkout_mirrors_origin() {
  local node="$1" account="$2" checkout="$3" verdict
  local target="$HEALTHCHECK_OPS_CHECKOUT"
  valid_abs_path "$target" || return 1
  verdict="$(checkout_mirror_verdict "$target")"
  case "$verdict" in
    mirror-clean) return 0 ;;
    mirror-unknown-remote)
      checkout_mirror_log "BEHIND-UNKNOWN: origin unreachable; ahead/dirty still checked"
      return 0 ;;
    *) checkout_mirror_log "$verdict"; return 1 ;;
  esac
}

run_check() {
  local definition="$1"
  local check_name probe_type node account target

  IFS='|' read -r check_name probe_type node account target <<< "$definition"
  case "$probe_type" in
    http_200) probe_http_200 "$node" "$account" "$target" ;;
    user_unit_active) probe_user_unit_active "$node" "$account" "$target" ;;
    http_unauth_401) probe_http_unauth_401 "$node" "$account" "$target" ;;
    embedding_health) probe_embedding_health "$node" "$account" "$target" ;;
    qdrant_health) probe_qdrant_health "$node" "$account" "$target" ;;
    mcp_health) probe_mcp_health "$node" "$account" "$target" ;;
    checkout_mirrors_origin) probe_checkout_mirrors_origin "$node" "$account" "$target" ;;
    *) log "ERROR: ${check_name} has unsupported probe type ${probe_type}"; return 1 ;;
  esac
}

main() {
  local -a checks=("${LIVE_CHECKS[@]}")
  local definition check_name probe_type
  local -a failed_checks=()
  local remote_total=0 remote_failed=0

  case "${1:-}" in
    "") ;;
    --synthetic-failure)
      checks=("synthetic nonexistent ops unit|user_unit_active|${HOST_A}|ops|autophagy-healthcheck-synthetic-does-not-exist.service")
      ;;
    *) usage ;;
  esac
  [[ "$#" -le 1 ]] || usage

  require_commands chmod date grep mkdir ssh tee timeout
  if [[ -n "$SSH_IDENTITY" && ! -r "$SSH_IDENTITY" ]]; then
    printf '[healthcheck] ERROR: SSH identity is not readable: %s\n' "$SSH_IDENTITY" >&2
    return 1
  fi
  setup_log
  log "mode=${1:-live} read_only=true"

  for definition in "${checks[@]}"; do
    IFS='|' read -r check_name probe_type _ <<< "$definition"
    [[ "$probe_type" == "checkout_mirrors_origin" ]] || remote_total=$(( remote_total + 1 ))
    if run_check "$definition"; then
      log "PASS ${check_name}"
    else
      log "FAIL ${check_name}"
      failed_checks+=("$definition")
      [[ "$probe_type" == "checkout_mirrors_origin" ]] || remote_failed=$(( remote_failed + 1 ))
    fi
  done

  if (( ${#failed_checks[@]} == 0 )); then
    log "ALL_HEALTHY"
    return 0
  fi

  # Every SSH-borne probe rides one transport, so all of them failing is a single
  # transport/credential fault, not N outages - ticketing each would bury the cause
  # under identical noise on that same broken path. The local checkout probe is
  # excluded from this tally: it needs no SSH, so its verdict is independent and
  # must not mask (or be masked by) a fleet-wide SSH outage. >1 keeps a single
  # deliberately-failing --synthetic-failure check on the ticket path.
  if (( remote_failed == remote_total && remote_total > 1 )); then
    log "ERROR: every remote check failed - suspect the shared SSH path, not ${remote_total} separate services"
    log "ERROR: resolved HEALTHCHECK_SSH_USER=${SSH_REMOTE_USER:-<none>} HEALTHCHECK_SSH_IDENTITY=${SSH_IDENTITY:-<none>}"
    log "INFRA_FAILURE"
    return 1
  fi

  for definition in "${failed_checks[@]}"; do
    IFS='|' read -r check_name probe_type _ <<< "$definition"
    report_repair "$check_name" "$probe_type" || log "REPAIR_TICKET_FAILED validation"
  done

  log "HEALTHCHECK_FAILED"
  return 1
}

main "$@"
