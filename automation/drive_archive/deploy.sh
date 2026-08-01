#!/usr/bin/env bash
# Deploy the drive-archive no-agent crons to the agent account (E11).
#
# Prereq: the node checkout ($AUTOPHAGY_DEPLOY_ROOT) must already contain
# automation/drive_archive/ — run `git pull --ff-only` there first. This script
# only installs the two ~/.hermes/scripts/ wrappers and registers the crons; it
# is idempotent (existing crons are left untouched).
#
# Reaction-only + no-agent contract: the producer POSTS a digest (never polls
# messages); the confirm watcher polls ONLY reactions. Both self-load
# ~/.env.secrets and pass credentials to their child via env= (규약 (b),(b-2)).
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
host="${DEPLOY_SSH_HOST:?DEPLOY_SSH_HOST is required — see .env.example}"

run_agent() {
  local script="$1"
  ssh "$host" "sudo -n -u agent -H bash -lc $(printf '%q' "$script")"
}

push_file() {
  local source="$1" destination="$2"
  run_agent "umask 077; mkdir -p \"\$HOME/$(dirname "$destination")\"; cat > \"\$HOME/$destination\"; chmod 600 \"\$HOME/$destination\"" < "$source"
}

# Deploy guard: refuse to push code that origin/main does not have (see the header of
# automation/deploy_provenance.sh for why a silent revert is otherwise inevitable).
source "$repo_root/automation/deploy_provenance.sh"
deploy_provenance_check "$repo_root" \
  "$repo_root/automation/drive_archive/cron/drive_archive_sync_request.py" \
  "$repo_root/automation/drive_archive/cron/drive_archive_confirm_reaction_watch.py" \
  "$repo_root/automation/drive_archive" || exit 4

push_file "$repo_root/automation/drive_archive/cron/drive_archive_sync_request.py" \
  '.hermes/scripts/drive_archive_sync_request.py'
push_file "$repo_root/automation/drive_archive/cron/drive_archive_confirm_reaction_watch.py" \
  '.hermes/scripts/drive_archive_confirm_reaction_watch.py'

# producer: hourly digest of changed tracked deliverables (posts only)
run_agent 'PATH="$HOME/.local/bin:$PATH"; if hermes cron list | grep -Eq "Name:[[:space:]]+drive-archive-sync-request$"; then exit 0; fi; hermes cron create "every 1h" --name drive-archive-sync-request --no-agent --script drive_archive_sync_request.py --deliver local'
# confirm watcher: reactions-only, gated upload on owner ✅
run_agent 'PATH="$HOME/.local/bin:$PATH"; if hermes cron list | grep -Eq "Name:[[:space:]]+drive-archive-confirm-watch$"; then exit 0; fi; hermes cron create "every 1m" --name drive-archive-confirm-watch --no-agent --script drive_archive_confirm_reaction_watch.py --deliver local'

run_agent 'PATH="$HOME/.local/bin:$PATH"; hermes cron list'
