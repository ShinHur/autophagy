#!/usr/bin/env bash
# automation/checkout_mirror_probe.sh — is the ops deploy checkout still a clean
# one-way mirror of origin/main? Sourced by healthcheck.sh (the DETECT half) and
# by land.sh (the CONVERGE half), so both judge drift by one rule. land.sh runs
# from the workstation, so it ships these functions to the node BY VALUE
# (declare -f) rather than sourcing the node's copy: since DG-6 a dirty mirror
# only warns, and executing that mirror's shell as ops would take the warning's
# safety case away.
#
# WHY it is its own file: healthcheck.sh sits 5 lines under the 250 pure-LOC gate,
# and the verdict logic plus its two recovery texts do not fit. Extracting them
# keeps healthcheck.sh under the ceiling and hands land.sh the same primitive.
#
# WHY it exists at all, three dated faults:
#   2026-07-27  a commit made INSIDE /srv/autophagy-agents stranded work nowhere
#               else and blocked every session's ff-pull  → detected as mirror-ahead.
#   2026-07-29  the SSH probe was allowlist-denied (rc=126) AND the nested
#               `sudo -n -u ops` was sudoers-denied (rc=126) — TWO stacked denials
#               on one command, so the probe never ran. Fix: run LOCALLY on the
#               cron host (the checkout is local there), needing neither ssh nor sudo.
#   2026-07-29  ops sat 11 commits BEHIND origin after another session's push, and
#               the old probe compared against its own stale ref  → detected as
#               mirror-behind via `git ls-remote` (a network READ that writes no
#               local ref, so the read-only invariant holds: never fetch/pull/reset).

checkout_mirror_log() { printf '[checkout-mirror] %s\n' "$*" >&2; }

# Print exactly one verdict word; return 0 only for mirror-clean. Order matters:
# dirty and ahead are graver, offline, and certain; behind needs the network and
# is skipped (mirror-unknown-remote) rather than guessed when the remote is unreachable.
checkout_mirror_verdict() { # checkout_mirror_verdict <checkout-path>
  local checkout="$1" remote head
  [[ -d "$checkout/.git" ]] || { echo "mirror-no-checkout"; return 1; }
  if [[ -n "$(git -C "$checkout" status --porcelain --untracked-files=no 2>/dev/null)" ]]; then
    echo "mirror-dirty"; return 1
  fi
  if ! git -C "$checkout" merge-base --is-ancestor HEAD origin/main 2>/dev/null; then
    echo "mirror-ahead"; return 1
  fi
  remote="$(timeout 20 git -C "$checkout" ls-remote origin refs/heads/main 2>/dev/null | awk '{print $1}')"
  if [[ -z "$remote" ]]; then
    echo "mirror-unknown-remote"; return 1
  fi
  head="$(git -C "$checkout" rev-parse HEAD 2>/dev/null)"
  if [[ "$remote" != "$head" ]]; then
    echo "mirror-behind"; return 1
  fi
  echo "mirror-clean"
}

# Non-destructive recovery text, chosen by verdict. Ahead/dirty commits exist
# nowhere else, so their text must never invite a discard; behind just needs a pull.
checkout_mirror_guidance() { # checkout_mirror_guidance <checkout-path>
  case "$(checkout_mirror_verdict "$1")" in
    mirror-behind)
      cat <<'BEHIND_EOF'
The ops deploy checkout is behind origin/main. Whether that means prod is stale
depends on the node: with the immutable release live it is only this observation
post that lagged; with no release installed it IS prod running stale code.
Converge it non-destructively from the workstation:
  workstation$  automation/land.sh      # push + converge the runtime, verified
or, if nothing is unpushed, just:
  here$         git pull --ff-only
BEHIND_EOF
      ;;
    *)
      cat <<'AHEAD_EOF'
The ops deploy checkout is a one-way mirror of origin/main: the only writes
allowed inside it are git fetch and git pull --ff-only. This failure means a
commit was made there, or a tracked file was edited there.
Recover WITHOUT discarding the work - it exists nowhere else:
  here$         git format-patch origin/main..HEAD
  workstation$  git am *.patch && git push origin main
  here$         git pull --ff-only
Never git reset --hard, git checkout --, or git stash first.
AHEAD_EOF
      ;;
  esac
}
