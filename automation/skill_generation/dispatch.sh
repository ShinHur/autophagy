#!/usr/bin/env bash
set -u -o pipefail

request_only=0
if [[ "${1:-}" == "--request-only" ]]; then
  request_only=1
  shift
fi
name="${1:-}"
[[ "$name" =~ ^auto-[0-9a-f]{16}$ ]] || { printf 'usage: dispatch.sh auto-<16hex>\n' >&2; exit 4; }
host="${DEPLOY_SSH_HOST:?DEPLOY_SSH_HOST is required — see .env.example}"
deploy_root="${AUTOPHAGY_DEPLOY_ROOT:?AUTOPHAGY_DEPLOY_ROOT is required — see .env.example}"
skills_root="${AUTOPHAGY_SKILLS_ROOT:?AUTOPHAGY_SKILLS_ROOT is required — see .env.example}"
e2e_mode="${E2E_TEST_MODE:-}"

# The node-side deploy-skill.sh needs both roots too, so forward them explicitly
# rather than relying on whatever the remote login shell happens to export.
ssh "$host" "E2E_TEST_MODE=$(printf '%q' "$e2e_mode") AUTOPHAGY_DEPLOY_ROOT=$(printf '%q' "$deploy_root") AUTOPHAGY_SKILLS_ROOT=$(printf '%q' "$skills_root") bash -s -- '$name' '$request_only'" <<'REMOTE'
set -u -o pipefail
name="$1"
request_only="$2"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
sudo -n -u agent -H tar -C /home/agent/.hermes/skill-generation/drafts -czf - "$name" | tar -xzf - -C "$stage"
mkdir -p "$stage/repo"
sudo -n -u agent -H tar -C "$AUTOPHAGY_DEPLOY_ROOT" -czf - automation/deploy-skill.sh automation/skill_gate.py automation/skill_review.py | tar -xzf - -C "$stage/repo"
arguments=()
if [[ "$request_only" == 1 ]]; then
  arguments+=(--request-only)
fi
E2E_TEST_MODE="$E2E_TEST_MODE" DEPLOY_SSH_HOST='' SKILL_PROPOSAL_SOURCE=auto SKILL_SRC_DIR="$stage/$name" bash "$stage/repo/automation/deploy-skill.sh" "$name" "${arguments[@]}"
result=$?
record_args=()
if [[ "$request_only" == 1 ]]; then
  record_args+=(--request-only)
fi
sudo -n -u agent -H python3 -I /home/agent/.hermes/skill-generation/runtime/automation/skill_generation/cli.py record-pipeline-result "$name" "$result" "${record_args[@]}"
exit "$result"
REMOTE
