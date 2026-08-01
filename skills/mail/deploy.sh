#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
host="${DEPLOY_SSH_HOST:?set DEPLOY_SSH_HOST}"

run_agent() {
  local script="$1"
  ssh "$host" "sudo -n -u agent -H bash -lc $(printf '%q' "$script")"
}

push_file() {
  local source="$1" destination="$2"
  run_agent "umask 077; mkdir -p \"\$HOME/$(dirname "$destination")\"; cat > \"\$HOME/$destination\"; chmod 600 \"\$HOME/$destination\"" < "$source"
}

source "$repo_root/automation/deploy_provenance.sh"
deploy_provenance_check "$repo_root" \
  "$repo_root/skills/mail/scripts/mail_digest_watch.py" || exit 4

push_file "$repo_root/skills/mail/scripts/mail_digest_watch.py" \
  '.hermes/scripts/mail_digest_watch.py'
run_agent 'PATH="$HOME/.local/bin:$PATH"; job_id=$(hermes cron list | awk "/^  [0-9a-f]+ \[/{id=\$1} /Name:[[:space:]]+mail-daily-digest$/{print id; exit}"); if [ -n "$job_id" ]; then hermes cron edit "$job_id" --deliver discord --no-agent --script mail_digest_watch.py; else hermes cron create "0 8 * * *" --name mail-daily-digest --no-agent --script mail_digest_watch.py --deliver discord; fi'
run_agent 'PATH="$HOME/.local/bin:$PATH"; hermes cron list'
