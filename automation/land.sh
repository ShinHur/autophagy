#!/usr/bin/env bash
# automation/land.sh — push to origin AND converge the node's runtime in ONE
# verified step, so the two can never silently drift apart.
#
# WHY (2026-07-29): a push whose node-sync was forgotten left prod 11 commits
# behind origin with nobody the wiser — the recurring "two steps done as one,
# one forgotten" fault. This fuses them and REFUSES to finish unless the runtime
# ends at the sha just pushed. Every refusal is non-destructive: it never
# rebases, resets, or discards. A half-landing is reported, never silent.
#
# WHAT "the runtime" means depends on the node, so the node decides (DG-6):
#   release mode  the release `current` path is a live symlink. The resident
#                 checkout is then only a drift observation post, so its dirt or
#                 stranded commits WARN instead of vetoing an unrelated landing
#                 — the fault that motivated the whole snapshot design. The hard
#                 post-condition is the release: `current` must end at dev HEAD.
#   fallback mode `current` is absent (the documented `rm` rollback). Every
#                 resolver falls back to the mirror, so the mirror IS production
#                 again and the pre-DG-6 hard contract stands unchanged.
# A `current` that exists but is broken is NEITHER: that is a corrupt node, and
# guessing "absent" there would silently demote a release node to its stale mirror.
#
# Env:
#   DEPLOY_SSH_HOST   ops node (required; empty = run ON that host) — see .env.example
#   LAND_ABI_STRICT=1 escalate a live-skill ABI break from WARN to a hard block
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIRROR_CHECKOUT="${AUTOPHAGY_DEPLOY_ROOT:?AUTOPHAGY_DEPLOY_ROOT is required — see .env.example}"
SKILLS_LIVE="${AUTOPHAGY_SKILLS_ROOT:?AUTOPHAGY_SKILLS_ROOT is required — see .env.example}"
# The release store lives beside the mirror; release_store.py owns the basenames.
RELEASE_STORE_PARENT="$(dirname "$MIRROR_CHECKOUT")"
RELEASE_CURRENT="$RELEASE_STORE_PARENT/autophagy-agent-current"
# One drift rule, two consumers: healthcheck.sh DETECTS, land.sh CONVERGES around
# the verdict. The functions are shipped to the node BY VALUE (declare -f) rather
# than sourced from its copy — sourcing would execute the very checkout whose
# dirt we just agreed to tolerate.
# shellcheck source=automation/checkout_mirror_probe.sh
source "$REPO_ROOT/automation/checkout_mirror_probe.sh"
SSH_HOST="${DEPLOY_SSH_HOST?DEPLOY_SSH_HOST is required (empty = this node) — see .env.example}"
[[ "$(hostname -s 2>/dev/null)" == "$SSH_HOST" ]] && SSH_HOST=""

land_log() { printf '[land] %s\n' "$*" >&2; }
land_block() { land_log "LAND-BLOCK: $1"; exit "${2:-1}"; }
# The mirror drifted but is not production: say so loudly, never fatally.
land_mirror_warn() { land_log "LAND-MIRROR-WARN: $1"; }
# The push already reached origin; only the node failed. Say so, and never imply
# the push was lost — the operator just needs to converge the node.
land_stranded() { land_log "pushed OK to origin/main, but the runtime was NOT converged ($1). re-run automation/land.sh."; exit 1; }

run_as() { # run_as <account> <script>
  local acct="$1" script="$2"
  if [[ -n "$SSH_HOST" ]]; then
    ssh "$SSH_HOST" "sudo -n -u $acct -H bash -c $(printf '%q' "$script")"
  else
    sudo -n -u "$acct" -H bash -c "$script"
  fi
}

# Resolved ON THE NODE: a workstation `test -e` would stat /srv on the wrong host
# and mistake a release node for a rollback one (deploy-skill.sh precedent).
node_probe_script() {
  declare -f checkout_mirror_log checkout_mirror_verdict checkout_mirror_guidance
  printf 'current=%q\nmirror=%q\n' "$RELEASE_CURRENT" "$MIRROR_CHECKOUT"
  cat <<'PROBE'
if [ -L "$current" ] && [ ! -e "$current" ]; then printf 'LAND-PROBE corrupt dangling-current\n'; exit 0; fi
if [ -e "$current" ] && [ ! -L "$current" ]; then printf 'LAND-PROBE corrupt current-is-not-a-symlink\n'; exit 0; fi
if [ -L "$current" ]; then mode=release; else mode=fallback; fi
verdict="$(checkout_mirror_verdict "$mirror")" || true
printf 'LAND-PROBE %s %s\n' "$mode" "$verdict"
[ "$verdict" = mirror-clean ] || checkout_mirror_guidance "$mirror"
PROBE
}

land_abi_probe() { # land_abi_probe <runtime_root>
  local runtime_root="$1" abi_rc=0
  run_as ops "python3 -I $runtime_root/automation/skill_library_abi.py $SKILLS_LIVE $runtime_root/automation" >/dev/null 2>&1 \
    || abi_rc=$?
  (( abi_rc == 0 )) && { printf 'ok'; return 0; }
  land_log "LAND-ABI-WARN: a live skill can no longer call the shared library (the deploy still landed)"
  [[ "${LAND_ABI_STRICT:-}" == "1" ]] && land_block "LAND_ABI_STRICT=1 and a live skill has an ABI break"
  printf 'warn'
}

land_release() { # land_release <expected_sha> <verdict> <guidance>
  local expected="$1" verdict="$2" guidance="$3"
  case "$verdict" in
    mirror-clean) : ;;
    mirror-behind)
      # Best effort only: the mirror is a monitoring surface now, so failing to
      # fast-forward it must not strand a landing production already has.
      run_as ops "git -C $MIRROR_CHECKOUT pull --ff-only" >/dev/null 2>&1 \
        || land_mirror_warn "the observation mirror could not fast-forward; production is unaffected" ;;
    *)
      land_mirror_warn "the resident checkout is no longer the runtime, but it has drifted ($verdict) — production is unaffected, this is not"
      [[ -n "$guidance" ]] && printf '%s\n' "$guidance" >&2 ;;
  esac

  # Pin the sha WE pushed. Left to re-read origin itself the converger would
  # install whatever landed most recently, which is a different landing.
  land_log "converging the release runtime to $expected"
  run_as ops "RELEASE_EXPECTED_SHA=$expected bash $RELEASE_CURRENT/automation/converge-release-runtime.sh" >/dev/null 2>&1 \
    || land_stranded "the release snapshot install/flip failed"

  # The snapshot pins origin BEFORE running its command, so another session can
  # land inside that window; a release pinned to a sha origin/main no longer
  # carries is not a landing, it is a fork.
  local remote_now
  remote_now="$(run_as ops "git -C $MIRROR_CHECKOUT ls-remote origin refs/heads/main" 2>/dev/null | awk '{print $1}')" \
    || land_stranded "transport error re-reading origin/main"
  [[ "$remote_now" == "$expected" ]] \
    || land_stranded "origin/main moved to ${remote_now:-<none>} while converging"

  run_as ops "python3 -I $RELEASE_CURRENT/automation/release_store.py current --verify $expected --store-root $RELEASE_STORE_PARENT" >/dev/null 2>&1 \
    || land_stranded "the runtime did not end at $expected"

  land_log "landed: origin/main=$expected runtime=release@$expected mirror=$verdict abi=$(land_abi_probe "$RELEASE_CURRENT")"
}

land_fallback() { # land_fallback <expected_sha> <verdict> <guidance>
  local expected="$1" verdict="$2" guidance="$3"
  case "$verdict" in
    mirror-dirty|mirror-ahead|mirror-no-checkout)
      [[ -n "$guidance" ]] && printf '%s\n' "$guidance" >&2
      land_block "no release runtime is installed, so $MIRROR_CHECKOUT IS production and it has drifted ($verdict) — resolve it on the node, never discard" ;;
  esac
  run_as ops "git -C $MIRROR_CHECKOUT pull --ff-only" >/dev/null 2>&1 \
    || land_stranded "the ff-pull failed"
  local mirror_head
  mirror_head="$(run_as ops "git -C $MIRROR_CHECKOUT rev-parse HEAD" 2>/dev/null || true)"
  [[ "$mirror_head" == "$expected" ]] \
    || land_block "the runtime checkout is not at origin/main after the pull (got ${mirror_head:-<none>}) — re-run automation/land.sh"
  land_log "landed: origin/main=$expected runtime=mirror@$mirror_head (no release installed) abi=$(land_abi_probe "$MIRROR_CHECKOUT")"
}

main() {
  git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || land_block "$REPO_ROOT is not a git checkout"
  [[ -z "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=no)" ]] \
    || land_block "dev checkout has uncommitted tracked changes — commit or stash first"

  git -C "$REPO_ROOT" fetch --quiet origin 2>/dev/null || true
  if [[ -n "$(git -C "$REPO_ROOT" rev-list HEAD..origin/main 2>/dev/null)" ]]; then
    land_block "dev checkout is behind origin/main — integrate first (never auto-rebased)"
  fi
  local dev_head
  dev_head="$(git -C "$REPO_ROOT" rev-parse HEAD)"

  # Push (a no-op when already equal). git push updates the local origin/main ref.
  git -C "$REPO_ROOT" push origin main >/dev/null 2>&1 \
    || land_block "git push origin main failed (non-ff race or no network) — the node is untouched"
  [[ "$(git -C "$REPO_ROOT" rev-parse origin/main 2>/dev/null)" == "$dev_head" ]] \
    || land_block "push did not land on origin/main — the node is untouched"

  # From here the push is DONE; any node failure is a stranded half-landing.
  local probe mode verdict guidance tag
  probe="$(run_as ops "$(node_probe_script)")" \
    || land_stranded "transport error reaching the node"
  read -r tag mode verdict <<<"$(printf '%s\n' "$probe" | head -n 1)"
  [[ "$tag" == "LAND-PROBE" ]] || land_stranded "the node probe returned no verdict"
  guidance="$(printf '%s\n' "$probe" | tail -n +2)"

  case "$mode" in
    release) land_release "$dev_head" "$verdict" "$guidance" ;;
    fallback) land_fallback "$dev_head" "$verdict" "$guidance" ;;
    *) land_stranded "$RELEASE_CURRENT is corrupt ($verdict) — neither a live release nor a clean rollback; repair the node first" ;;
  esac
}

main "$@"
