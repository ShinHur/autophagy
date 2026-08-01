#!/usr/bin/env bash
# automation/provision-release-store.sh — install the root-only release helper and
# create the immutable release store root.
#
# WHY it is its OWN file (2026-07-31): the release/runtime-root work must not touch
# automation/bootstrap-accounts.sh, which the active repair-report-rollout plan
# claims as its sole source change (collision C2). This provisioner mirrors
# provision-readonly-skills.sh instead: create /srv/autophagy-agent-releases
# (0755 root:root), install automation/release_store.py as the privileged helper,
# and install the sudoers stanza that lets ops call it. Idempotent.
#
# Env (test seams; default to the real node paths):
#   RELEASE_STORE_ROOT             default /srv/autophagy-agent-releases
#   HELPER_PATH                    default /usr/local/libexec/autophagy-install-release
#   SUDOERS_PATH                   default /etc/sudoers.d/autophagy-release-store
#   RELEASE_PROVISION_ASSUME_ROOT  override the root check for hermetic tests
set -euo pipefail

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly RELEASE_STORE_ROOT="${RELEASE_STORE_ROOT:-/srv/autophagy-agent-releases}"
readonly HELPER_PATH="${HELPER_PATH:-/usr/local/libexec/autophagy-install-release}"
readonly SUDOERS_PATH="${SUDOERS_PATH:-/etc/sudoers.d/autophagy-release-store}"

log() { printf '[provision-release-store] %s\n' "$*"; }
die() { log "ERROR: $1" >&2; exit 1; }

is_root() {
  if [[ -n "${RELEASE_PROVISION_ASSUME_ROOT:-}" ]]; then
    [[ "$RELEASE_PROVISION_ASSUME_ROOT" == "1" ]]
  else
    [[ "$EUID" == 0 ]]
  fi
}
is_root || die "run as root: sudo bash automation/provision-release-store.sh"

for command_name in install python3 visudo; do
  command -v "$command_name" >/dev/null || die "required command missing: $command_name"
done
[[ -f "$REPO_ROOT/automation/release_store.py" ]] || die "release_store.py missing"

# Store root and helper install dir (idempotent: install -d is a no-op if present).
install -d -m 0755 -o root -g root "$(dirname "$HELPER_PATH")" "$RELEASE_STORE_ROOT"

# Install the privileged helper by value; re-running replaces the single path.
install -m 0755 -o root -g root "$REPO_ROOT/automation/release_store.py" "$HELPER_PATH"

# Sudoers stanza: install the tracked source (idempotent; install -m 0440 replaces
# the single path each run). The stanza references the fixed HELPER install path.
sudoers_src="$REPO_ROOT/automation/sudoers.d/autophagy-release-store"
[[ -f "$sudoers_src" ]] || die "tracked sudoers source missing: $sudoers_src"
install -d -m 0755 -o root -g root "$(dirname "$SUDOERS_PATH")"
install -m 0440 -o root -g root "$sudoers_src" "$SUDOERS_PATH"
visudo -cf "$SUDOERS_PATH" >/dev/null

log "READY store_root=$RELEASE_STORE_ROOT helper=$HELPER_PATH sudoers=$SUDOERS_PATH"
