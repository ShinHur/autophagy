#!/usr/bin/env bash
#=============================================================================
# automation/bootstrap-accounts.sh — node account provisioning
#
# Provisions the service-account structure on the deployment nodes:
#
#   production node: agent (the owner's primary agent)
#                    peer  (test peer agent)
#                    ops   (infra / repair / hub)
#   rag node:        ops   only
#
# WHAT IT DOES (per role):
#   [all roles]
#     - useradd -m -s /bin/bash for each account (idempotent: skips existing)
#     - loginctl enable-linger + verify Linger=yes
#     - ~<user>/.env.secrets created EMPTY, mode 600, owned by that user
#       (real secrets are added by later tasks W0-6/W1-1 — NEVER by this script)
#     - home directory forced to mode 700. This is the actual isolation
#       mechanism ("3계정 상호 시크릿 읽기 불가", plan constraint 5): with the
#       home itself at 700, other accounts cannot even traverse into it, so
#       the 600 on .env.secrets is defense-in-depth, not the only barrier.
#       Set explicitly because useradd's default home mode varies by distro.
#   [production only]
#     - group 'autophagy' + members agent, peer (read audience for checkout)
#     - ~agent/{wiki,notes,patent-drafts,outputs,mail} skeleton, each 700
#       (plan constraint 8 — populated later by W2-2/W5-1/W5-3/4/5/W4-2)
#     - $AUTOPHAGY_PRIVATE_ROOT/{runtime-logs,repair-logs}  ops:ops 700
#     - $AUTOPHAGY_DEPLOY_ROOT                              ops:autophagy 2750
#     - gitleaks 8.30.1 (linux_arm64) system-wide at /usr/local/bin/gitleaks
#     - per-account git config: safe.directory + placeholder identity
#     - ops deploy key (~ops/.ssh/id_ed25519) + clone/pull of the repo
#     - commit-refusal pre-commit hook in $AUTOPHAGY_DEPLOY_ROOT/.git/hooks
#
# USAGE (run ON the target node, as root — the owner runs this personally; it
# stays a manual step because sudo on both nodes requires an interactive password):
#
#   production node:  sudo bash bootstrap-accounts.sh production
#   RAG node:         sudo bash bootstrap-accounts.sh rag
#
# Getting the script onto a node for the first run (the deploy checkout that
# would normally carry it does not exist yet — chicken and egg):
#
#   scp automation/bootstrap-accounts.sh "$ADMIN_USER@$NODE_HOST":/tmp/
#   ssh "$ADMIN_USER@$NODE_HOST"
#   sudo bash /tmp/bootstrap-accounts.sh production
#
# TWO-PHASE FLOW (production only; rag completes in a single run):
#   Run 1: provisions everything up to the deploy key, then PRINTS the public
#          key and EXITS 0. A human must register it as a READ-ONLY Deploy Key
#          key and EXITS 0. A human must register it as a READ-ONLY Deploy Key
#          on the repository's deploy-key settings page (printed by the script)
#          (this script cannot do that: 'ops' has no authenticated gh, and
#          deploy-key registration needs repo admin — deliberately human).
#   Run 2: detects working key auth, clones the repo to $AUTOPHAGY_DEPLOY_ROOT
#          (or pulls if present), installs the commit-refusal hook. Done.
#
# The script is FULLY IDEMPOTENT — safe to re-run any number of times:
# every resource is check-before-create; .env.secrets is never truncated;
# git identity is only set if unset (the owner's later customization survives).
#
# Keep the runbook + verification commands with your deployment inventory.
#=============================================================================
set -Eeuo pipefail

readonly GITLEAKS_VERSION="8.30.1"
readonly GROUP_NAME="autophagy"
# accept-new = trust-on-first-use for github.com's host key (no interactive
# prompt mid-script). Paranoid option: pre-pin fingerprints from
# https://api.github.com/meta into ~ops/.ssh/known_hosts before run 2.
readonly GIT_SSH_CMD="ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)

log()  { echo "[bootstrap] $*"; }
warn() { echo "[bootstrap] WARN: $*" >&2; }
die()  { echo "[bootstrap] ERROR: $*" >&2; exit 1; }
banner() { echo; echo "===== $* ====="; }
trap 'echo "[bootstrap] FAILED at line $LINENO: $BASH_COMMAND" >&2' ERR

usage() {
  cat >&2 <<'EOF'
Usage: sudo bash bootstrap-accounts.sh <production|rag>

  production  primary node: accounts agent/peer/ops + group/dirs/deploy checkout
  rag         RAG node:     account ops only (linger + .env.secrets + home 700)
EOF
  exit 2
}

require_cmds() {
  local c
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || die "required command not found: $c"
  done
}

# Deployment-specific configuration. Required for the production role only: the
# RAG node has no repository checkout and no shared deploy/private roots, so it
# must not be forced to invent values it will never use. Every value is required
# — there is no default, because a wrong guess here provisions the wrong host.
# `readonly` inside a function still defines a global, so callees see these.
require_production_config() {
  : "${AUTOPHAGY_REPO_SLUG:?AUTOPHAGY_REPO_SLUG is required — see .env.example}"
  : "${AUTOPHAGY_DEPLOY_ROOT:?AUTOPHAGY_DEPLOY_ROOT is required — see .env.example}"
  : "${AUTOPHAGY_PRIVATE_ROOT:?AUTOPHAGY_PRIVATE_ROOT is required — see .env.example}"
  readonly REPO_SSH_URL="git@github.com:${AUTOPHAGY_REPO_SLUG}.git"
  readonly REPO_KEYS_URL="https://github.com/${AUTOPHAGY_REPO_SLUG}/settings/keys"
  readonly DEPLOY_DIR="$AUTOPHAGY_DEPLOY_ROOT"
  readonly PRIVATE_DIR="$AUTOPHAGY_PRIVATE_ROOT"
  # Comment string for the ops deploy key. The node's own hostname keeps it
  # distinguishable in the repository's deploy-key list without hardcoding one.
  readonly DEPLOY_KEY_COMMENT="ops@$(hostname -s)-autophagy-deploy"
}

#-----------------------------------------------------------------------------
# Accounts: create + linger + home 700 + ~/.env.secrets 600
#-----------------------------------------------------------------------------
ensure_account() {
  local u="$1" desc="$2" home pg sec linger

  if id "$u" >/dev/null 2>&1; then
    log "account '$u': already exists — skipping useradd"
  else
    # Regular login accounts (NOT --system): later tasks run Hermes/OpenClaw
    # instances under them (W1-2/W1-3/W3-4/W6-2), which want normal shells,
    # home dirs and systemd user managers.
    useradd -m -s /bin/bash -c "$desc" "$u"
    log "account '$u': created"
  fi

  home="$(getent passwd "$u" | cut -d: -f6)"
  [[ -d "$home" ]] || die "home directory for '$u' not found: $home"
  pg="$(id -gn "$u")"

  # Isolation: home itself must be 700 (do NOT rely on distro default 755/750).
  chown "$u:$pg" "$home"
  chmod 700 "$home"
  log "account '$u': home $home enforced 700 ($u:$pg)"

  # Linger: user services may run without an active login session.
  loginctl enable-linger "$u"
  linger="$(loginctl show-user "$u" --property=Linger --value 2>/dev/null || true)"
  if [[ "$linger" == "yes" || -e "/var/lib/systemd/linger/$u" ]]; then
    log "account '$u': Linger=yes"
  else
    die "linger verification failed for '$u' (got: '${linger:-<none>}')"
  fi

  # Empty secrets placeholder. NEVER truncate an existing file — later tasks
  # (W0-6, W1-1, ...) write real values into it; re-runs only enforce perms.
  sec="$home/.env.secrets"
  if [[ ! -f "$sec" ]]; then
    install -m 600 -o "$u" -g "$pg" /dev/null "$sec"
    log "account '$u': created empty $sec (600)"
  else
    log "account '$u': $sec exists — enforcing 600/ownership only"
  fi
  chown "$u:$pg" "$sec"
  chmod 600 "$sec"
}

#-----------------------------------------------------------------------------
# Production: group, agent home skeleton, deployment root dirs
#-----------------------------------------------------------------------------
provision_group() {
  local u
  groupadd -f "$GROUP_NAME"
  log "group '$GROUP_NAME': present"
  # agent + peer read the shared checkout via this group. ops is not added:
  # it OWNS the checkout, owner bits already grant full access.
  for u in agent peer; do
    if id -nG "$u" | tr ' ' '\n' | grep -qx "$GROUP_NAME"; then
      log "group '$GROUP_NAME': '$u' already a member"
    else
      usermod -aG "$GROUP_NAME" "$u"
      log "group '$GROUP_NAME': added '$u'"
    fi
  done
}

provision_agent_skeleton() {
  local home d
  home="$(getent passwd agent | cut -d: -f6)"
  # Personal sensitive material lives in agent's 700 home (plan constraint 8).
  # Empty skeleton only; populated by W2-2 (wiki), W5-1 (notes),
  # W5-3/4/5 (patent-drafts, outputs), W4-2 (mail).
  for d in wiki notes patent-drafts outputs mail; do
    install -d -m 700 -o agent -g "$(id -gn agent)" "$home/$d"
  done
  log "agent skeleton: $home/{wiki,notes,patent-drafts,outputs,mail} (700)"
}

provision_root_dirs() {
  # Protected private paths: ops-only, nothing for group/others.
  install -d -m 700 -o ops -g "$(id -gn ops)" \
    "$PRIVATE_DIR" "$PRIVATE_DIR/runtime-logs" "$PRIVATE_DIR/repair-logs"
  log "private dirs: $PRIVATE_DIR/{runtime-logs,repair-logs} (ops, 700)"

  # Shared deploy checkout root. Mode 2750, reasoning:
  #   - owner ops rwx           : ops clones/pulls/commits (full read-write)
  #   - group autophagy r-x     : agent/peer can list + read + traverse, but
  #                               CANNOT create/delete/modify (no group write)
  #   - others ---              : outside the group nothing is even visible;
  #                               this outer gate is why inner file modes
  #                               (644 from ops's umask) don't leak anything
  #   - setgid (the leading 2)  : files/dirs git creates inside inherit the
  #                               'autophagy' group automatically, so group
  #                               readability survives pulls without needing
  #                               recursive chgrp fixups on every update
  install -d -m 2750 -o ops -g "$GROUP_NAME" "$DEPLOY_DIR"
  log "deploy dir: $DEPLOY_DIR (ops:$GROUP_NAME, 2750 setgid)"
}

#-----------------------------------------------------------------------------
# Production: gitleaks binary (aarch64) — the tarball is selected per
# architecture below; pin the version in one place and verify it after install.
#-----------------------------------------------------------------------------
install_gitleaks() {
  local current arch tmpd url
  if [[ -x /usr/local/bin/gitleaks ]]; then
    current="$(/usr/local/bin/gitleaks version 2>/dev/null || echo unknown)"
    if [[ "$current" == "$GITLEAKS_VERSION" ]]; then
      log "gitleaks: $GITLEAKS_VERSION already at /usr/local/bin/gitleaks — skipping"
      return 0
    fi
    warn "gitleaks: found version '$current', reinstalling pinned $GITLEAKS_VERSION"
  fi

  case "$(uname -m)" in
    aarch64|arm64) arch="arm64" ;;  # DGX Spark nodes
    x86_64)        arch="x64"   ;;  # defensive: correct tarball elsewhere too
    *) die "unsupported architecture: $(uname -m)" ;;
  esac

  url="https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${arch}.tar.gz"
  tmpd="$(mktemp -d)"
  log "gitleaks: downloading $url"
  curl -sL -o "$tmpd/gitleaks.tar.gz" "$url"
  tar -xzf "$tmpd/gitleaks.tar.gz" -C "$tmpd"
  # /usr/local/bin: root-writable, on every account's default PATH.
  install -m 755 "$tmpd/gitleaks" /usr/local/bin/gitleaks
  rm -rf "$tmpd"
  log "gitleaks: installed $(/usr/local/bin/gitleaks version) at /usr/local/bin/gitleaks"
}

#-----------------------------------------------------------------------------
# Production: per-account git config (safe.directory + identity)
#-----------------------------------------------------------------------------
configure_git_account() {
  local u="$1"
  # git refuses to touch a repo owned by another user unless safe.directory
  # is set — required for agent/peer on the ops-owned checkout (and harmless
  # for ops itself). --add is guarded to avoid duplicate entries on re-runs.
  if ! sudo -u "$u" -H git config --global --get-all safe.directory 2>/dev/null \
      | grep -qx "$DEPLOY_DIR"; then
    sudo -u "$u" -H git config --global --add safe.directory "$DEPLOY_DIR"
    log "git ($u): safe.directory += $DEPLOY_DIR"
  else
    log "git ($u): safe.directory already set"
  fi

  # Placeholder identity — the owner may want to customize these later; only set
  # when unset so re-runs never clobber a customized value.
  if ! sudo -u "$u" -H git config --global user.name >/dev/null 2>&1; then
    sudo -u "$u" -H git config --global user.name "$u (autophagy-agents)"
    log "git ($u): user.name set to placeholder"
  fi
  if ! sudo -u "$u" -H git config --global user.email >/dev/null 2>&1; then
    sudo -u "$u" -H git config --global user.email "$u@example.invalid"
    log "git ($u): user.email set to placeholder"
  fi
}

#-----------------------------------------------------------------------------
# Production: deploy key, auth gate, checkout, commit-refusal hook
#-----------------------------------------------------------------------------
ensure_deploy_key() {
  # Runs entirely as ops (-H => HOME=~ops, so ~ resolves to ops's home).
  # -N "" : no passphrase — key is confined to ops's 700 home and is meant
  #         for unattended pulls; GitHub side is registered READ-ONLY.
  sudo -u ops -H bash -c '
    set -euo pipefail
    umask 077
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    if [[ ! -f ~/.ssh/id_ed25519 ]]; then
      ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C "$1"
      echo "[bootstrap]   deploy key generated: ~/.ssh/id_ed25519"
    else
      echo "[bootstrap]   deploy key already exists: ~/.ssh/id_ed25519"
    fi
  ' bootstrap-deploy-key "$DEPLOY_KEY_COMMENT"
}

github_auth_ok() {
  # `ssh -T git@github.com` exits 1 even on success; the success marker is
  # the "successfully authenticated" greeting, so parse output instead.
  local out
  out="$(sudo -u ops -H ssh "${SSH_OPTS[@]}" -T git@github.com 2>&1 || true)"
  [[ "$out" == *"successfully authenticated"* ]]
}

print_key_registration_banner() {
  local ops_home pub
  ops_home="$(getent passwd ops | cut -d: -f6)"
  pub="$(cat "$ops_home/.ssh/id_ed25519.pub")"
  cat <<EOF

==============================================================================
 PHASE 1 COMPLETE — HUMAN ACTION REQUIRED (deploy key not registered yet)
==============================================================================
 ops deploy PUBLIC key:

   $pub

 1) Open:  $REPO_KEYS_URL
 2) "Add deploy key"
      Title: $DEPLOY_KEY_COMMENT
      Key:   paste the single line above
      [ ] Allow write access   <-- LEAVE UNCHECKED (read-only Deploy Key)
 3) Re-run this script on this node to complete the checkout:
      sudo bash bootstrap-accounts.sh production

 (This registration needs a human with repo admin access — the script
  intentionally does not attempt it: 'ops' has no authenticated gh CLI.)
==============================================================================
EOF
}

do_checkout() {
  if [[ -d "$DEPLOY_DIR/.git" ]]; then
    log "checkout: repo present — pulling as ops (--ff-only: deploy checkout must never merge)"
    sudo -u ops -H env GIT_SSH_COMMAND="$GIT_SSH_CMD" \
      git -C "$DEPLOY_DIR" pull --ff-only
  else
    if [[ -n "$(ls -A "$DEPLOY_DIR" 2>/dev/null)" ]]; then
      die "$DEPLOY_DIR is non-empty but not a git repo — inspect manually before re-running"
    fi
    log "checkout: cloning $REPO_SSH_URL -> $DEPLOY_DIR as ops"
    sudo -u ops -H env GIT_SSH_COMMAND="$GIT_SSH_CMD" \
      git clone "$REPO_SSH_URL" "$DEPLOY_DIR"
  fi
  # Re-assert the outer gate after git activity (belt and braces).
  chown "ops:$GROUP_NAME" "$DEPLOY_DIR"
  chmod 2750 "$DEPLOY_DIR"
  log "checkout: up to date; $DEPLOY_DIR perms re-asserted (ops:$GROUP_NAME 2750)"
}

install_commit_refusal_hook() {
  # The deploy checkout is a ONE-WAY MIRROR of origin/main (root AGENTS.md,
  # "ops 체크아웃 단방향 규칙"): the only writes allowed inside it are git fetch and
  # git pull --ff-only. A commit made here runs in production but never reaches
  # git — the next deploy from a clean checkout silently reverts it — and until
  # someone untangles it the divergence blocks every session's ff-pull. So this
  # hook does not scan and does not judge: it refuses, unconditionally.
  #
  # It supersedes the gitleaks pre-commit hook that used to live here. That is
  # not a weakening: a commit that cannot happen cannot leak a secret, and
  # gitleaks still guards the workstation checkouts, where commits belong.
  #
  # Idempotent by construction — install(1) replaces the one target path, so a
  # re-run leaves exactly one hook and no backup files.
  #
  # git fetch and git pull --ff-only are untouched: neither creates a commit, so
  # neither runs pre-commit.
  local deploy_dir="${1:?deploy checkout path required}"
  local hook="$deploy_dir/.git/hooks/pre-commit" tmp
  tmp="$(mktemp)"
  cat > "$tmp" <<'HOOK_EOF'
#!/usr/bin/env bash
# Refuse every commit made inside the ops deploy checkout.
# Installed by automation/bootstrap-accounts.sh — root AGENTS.md "ops 체크아웃 단방향 규칙".
set -u

cat >&2 <<'REFUSAL_EOF'
[pre-commit] REFUSED — this is the ops deploy checkout, not a place to commit.

  It is a one-way mirror of origin/main. The only writes allowed here are
  git fetch and git pull --ff-only. A commit made here runs in production but
  never reaches git: the next deploy from a clean checkout silently reverts it,
  and until then the divergence blocks every session's ff-pull.

  Commit in the workstation checkout instead, then deploy from origin/main:

      workstation$  git commit ...  &&  git push origin main
      here$         git pull --ff-only

  Already have work here? It exists nowhere else — do NOT discard it. Move it
  out with author and history intact, then realign:

      here$         git format-patch origin/main..HEAD
      workstation$  git am *.patch  &&  git push origin main
      here$         git pull --ff-only

  Never git reset --hard, git checkout --, or git stash first.
REFUSAL_EOF
exit 1
HOOK_EOF
  # owner ops with 755: ops is the account git runs as in this checkout, and
  # group-readability is harmless — the group has no write access to .git.
  install -m 755 -o ops -g "$GROUP_NAME" "$tmp" "$hook"
  rm -f "$tmp"
  log "hook: commit-refusal pre-commit installed at $hook (ops, 755)"
}

#-----------------------------------------------------------------------------
# Summary — prints the evidence to keep as the provisioning record
#-----------------------------------------------------------------------------
print_summary() {
  local u home
  banner "SUMMARY (role=$ROLE, host=$(hostname))"
  getent passwd "${ACCOUNTS[@]}"
  for u in "${ACCOUNTS[@]}"; do
    home="$(getent passwd "$u" | cut -d: -f6)"
    echo "--- $u"
    loginctl show-user "$u" --property=Linger 2>/dev/null \
      || echo "Linger=file:$(test -e "/var/lib/systemd/linger/$u" && echo yes || echo no)"
    ls -ld "$home"
    ls -l "$home/.env.secrets"
  done
  if [[ "$ROLE" == "production" ]]; then
    echo "--- deployment roots"
    ls -ld "$PRIVATE_DIR" "$PRIVATE_DIR/runtime-logs" "$PRIVATE_DIR/repair-logs" "$DEPLOY_DIR"
    echo "--- gitleaks"
    /usr/local/bin/gitleaks version 2>/dev/null || echo "gitleaks: NOT INSTALLED"
  fi
  echo
  log "keep this output with your deployment inventory as the provisioning record"
}

#-----------------------------------------------------------------------------
# Main
#-----------------------------------------------------------------------------
ROLE="${1:-}"
case "$ROLE" in
  production) ACCOUNTS=(agent peer ops); require_production_config ;;
  rag)        ACCOUNTS=(ops) ;;
  *) usage ;;
esac

[[ "$(id -u)" -eq 0 ]] || die "must run as root: sudo bash bootstrap-accounts.sh $ROLE"

require_cmds useradd groupadd usermod loginctl getent install id
if [[ "$ROLE" == "production" ]]; then
  require_cmds git curl tar ssh ssh-keygen sudo
fi

banner "bootstrap — role=$ROLE host=$(hostname) arch=$(uname -m)"

banner "[1/8] accounts + linger + home 700 + .env.secrets 600"
case "$ROLE" in
  production)
    ensure_account agent "autophagy agent (owner primary agent)"
    ensure_account peer  "autophagy test peer agent"
    ensure_account ops   "autophagy infra/repair/hub operations"
    ;;
  rag)
    ensure_account ops   "autophagy infra/repair/hub operations"
    ;;
esac

if [[ "$ROLE" == "rag" ]]; then
  log "rag role: phases 2-8 are production-only — done."
  print_summary
  log "DONE (role=rag)"
  exit 0
fi

banner "[2/8] group '$GROUP_NAME' + membership (agent, peer)"
provision_group

banner "[3/8] agent home skeleton (constraint 8)"
provision_agent_skeleton

banner "[4/8] protected dirs $PRIVATE_DIR (ops 700)"
banner "[5/8] deploy dir $DEPLOY_DIR (ops:$GROUP_NAME 2750)"
provision_root_dirs

banner "[6/8] gitleaks $GITLEAKS_VERSION (system-wide)"
install_gitleaks

banner "[7/8] per-account git config (safe.directory + identity)"
for u in "${ACCOUNTS[@]}"; do
  configure_git_account "$u"
done

banner "[8/8] deploy key -> GitHub auth gate -> checkout -> commit-refusal hook"
ensure_deploy_key
if github_auth_ok; then
  log "GitHub deploy-key auth OK (ops)"
  do_checkout
  install_commit_refusal_hook "$DEPLOY_DIR"
else
  print_key_registration_banner
  print_summary
  log "PHASE 1 done — re-run after registering the deploy key (exit 0, by design)"
  exit 0
fi

print_summary
log "DONE (role=production) — all phases complete"
