#!/usr/bin/env bash
# automation/deploy_provenance.sh — shared deploy guard: never deploy code that is not in git.
#
# WHY (2026-07-25 선례): every deploy script copies files from the LOCAL checkout to
# prod. With parallel sessions a file is easily deployed while still uncommitted, or
# committed but not pushed. Prod then runs code that does not exist in origin/main —
# and the next deploy from any clean checkout SILENTLY REVERTS it. That is how the
# mail_digest_watch.py DNS-retry fix nearly got lost, and it is the same class as the
# 2026-07-21 incident where an old checkout overwrote a newer session's decision.
#
# The check is a pure content comparison: the working-tree blob hash of each file must
# equal the blob hash of the same path in the deploy reference (default origin/main).
# One comparison therefore catches BOTH "not committed" and "committed but not pushed".
#
# Usage (from a deploy script):
#   source "$repo_root/automation/deploy_provenance.sh"
#   deploy_provenance_check "$repo_root" <file-or-dir>...   # non-zero exit => do not deploy
#
# Env:
#   DEPLOY_PROVENANCE_REF   deploy reference (default: origin/main)
#   DEPLOY_ALLOW_UNPUSHED=1 skip the check — sandbox/testing ONLY, prints a warning.
#                           Never set it to "just get the deploy through": prod would
#                           run code no one else can reproduce or redeploy.

deploy_provenance_log() { printf '[deploy-provenance] %s\n' "$*" >&2; }

deploy_provenance_check() { # deploy_provenance_check <repo_root> <file-or-dir>...
  local repo_root="$1"
  shift || true
  if [[ "${DEPLOY_ALLOW_UNPUSHED:-}" == "1" ]]; then
    deploy_provenance_log "WARNING: DEPLOY_ALLOW_UNPUSHED=1 — provenance check skipped (sandbox only)"
    return 0
  fi
  [[ $# -gt 0 ]] || { deploy_provenance_log "DEPLOY-BLOCK: no paths given to check"; return 1; }
  git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || { deploy_provenance_log "DEPLOY-BLOCK: $repo_root is not a git checkout"; return 1; }

  local reference="${DEPLOY_PROVENANCE_REF:-origin/main}"
  timeout 20 git -C "$repo_root" fetch --quiet "${reference%%/*}" >/dev/null 2>&1 || true
  git -C "$repo_root" rev-parse --verify --quiet "$reference" >/dev/null \
    || { deploy_provenance_log "DEPLOY-BLOCK: deploy reference $reference is unavailable"; return 1; }

  local -a targets=()
  local path
  for path in "$@"; do
    if [[ -d "$path" ]]; then
      local tracked
      tracked="$(git -C "$repo_root" ls-files -- "$path")" || {
        deploy_provenance_log "DEPLOY-BLOCK: cannot list tracked files under $path"; return 1; }
      [[ -n "$tracked" ]] || { deploy_provenance_log "DEPLOY-BLOCK: $path has no tracked files"; return 1; }
      while IFS= read -r tracked_path; do targets+=("$tracked_path"); done <<<"$tracked"
    else
      local relative
      relative="$(git -C "$repo_root" ls-files --full-name --error-unmatch -- "$path" 2>/dev/null)" || {
        deploy_provenance_log "DEPLOY-BLOCK: $path is untracked — commit and push it before deploying"
        return 1; }
      targets+=("$relative")
    fi
  done

  local relative local_blob reference_blob
  for relative in "${targets[@]}"; do
    local_blob="$(git -C "$repo_root" hash-object -- "$repo_root/$relative" 2>/dev/null)" || {
      deploy_provenance_log "DEPLOY-BLOCK: cannot hash $relative"; return 1; }
    reference_blob="$(git -C "$repo_root" rev-parse --verify --quiet "$reference:$relative")" || {
      deploy_provenance_log "DEPLOY-BLOCK: $relative is missing from $reference — push it before deploying"
      return 1; }
    if [[ "$local_blob" != "$reference_blob" ]]; then
      deploy_provenance_log "DEPLOY-BLOCK: $relative differs from $reference — commit and push it first"
      deploy_provenance_log "  prod would run code absent from git, and the next clean deploy would revert it"
      deploy_provenance_log "  (sandbox testing only: re-run with DEPLOY_ALLOW_UNPUSHED=1)"
      return 1
    fi
  done
  deploy_provenance_log "OK: ${#targets[@]} file(s) match $reference"
  return 0
}
