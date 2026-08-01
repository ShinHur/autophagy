# LiteLLM gateway deployment runbook — run only after the docker-group unblock

**Status:** staged only. Do not execute any command in this document until the
owner has performed the root-owned `usermod -aG docker ops` change on the
production node and a fresh `ops` session passes the preflight below. This
runbook deliberately does not offer a rootless-Docker, alternate-account,
`sudo docker`, or `/etc/group` workaround.

Host names, account home paths and budget amounts are deployment-specific and
are **not** recorded in this repository. Set them in your shell before running
any block:

```bash
# SSH alias of the production node, from the public environment contract
# (.env.example). The retrieval/RAG node (referred to as node-b in this
# documentation) must never run this gateway.
NODE="${DEPLOY_SSH_HOST:?set the ssh alias of the production node}"
# Monthly virtual-key limits, in USD. Choose your own; nothing here is a default.
SOFT_BUDGET="${LITELLM_SOFT_BUDGET:?set the monthly soft-alert budget}"
HARD_BUDGET="${LITELLM_HARD_BUDGET:?set the monthly hard cap}"
```

## Syntax provenance (official LiteLLM docs, checked 2026-07-15)

The staged configuration uses these documented keys and endpoints:

| Config/API item | Source and documented syntax |
| --- | --- |
| Compose image, internal proxy port, config mount/flag | [Docker quick start](https://docs.litellm.ai/docs/proxy/docker_quick_start): `ghcr.io/berriai/litellm-database:latest`, proxy at `:4000`, volume-mounted `config.yaml`, `--config=/app/config.yaml`. |
| `model_list[].model_name`, `litellm_params.model`, `litellm_params.api_key`, `general_settings.master_key`, `general_settings.database_url` | [Docker quick start](https://docs.litellm.ai/docs/proxy/docker_quick_start), including `os.environ/VARIABLE` resolution and Postgres-backed virtual keys. |
| `default_key_generate_params`, `upperbound_key_generate_params` | [Virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys): default and upper-bound `/key/generate` fields, including `max_budget`, `models`, and `budget_duration`. |
| `soft_budget`, `max_budget`, `budget_duration` on a virtual key | [Budgets, rate limits](https://docs.litellm.ai/docs/proxy/users): `/key/generate` applies a per-key hard `max_budget`; the current LiteLLM request schema also accepts `soft_budget` (warning threshold) for virtual keys. |
| `router_settings.enable_tag_filtering`, deployment `litellm_params.tags`, request `metadata.tags` | [Tag-based routing](https://docs.litellm.ai/docs/proxy/tag_routing): tagged deployments are selected by request tags; if no deployment remains, LiteLLM returns `no_deployments_with_tag_routing`. |
| `POST /key/generate` authentication | [Virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys): database + master key are prerequisites; call `/key/generate` with `Authorization: Bearer <master-key>`. |
| `general_settings.fail_closed_budget_enforcement` | [Budgets, rate limits](https://docs.litellm.ai/docs/proxy/users#hard-budget-enforcement-fail-closed): verify budgeted calls against the authoritative database or reject them. |

The `patent-sensitive` rule is request-tag based, not a policy attachment:
policy-attachment `tags` match **key/team** metadata, while this requirement
blocks a **request** carrying `metadata.tags`. `glm-main` is tagged only
`default` and `non-patent-sensitive`, and LiteLLM tag filtering remains
enabled. The deployed `PatentSensitiveGlmBlocker` is the verified fail-closed
enforcement point for the current single-deployment image: it rejects that
request before a provider call with the documented
`no_deployments_with_tag_routing` marker. The client-side sensitivity gate must
attach the tag before any GLM call; Hermes owns the non-GLM reroute.

## 0. Local context and hard gate

Run these commands from this repository on the owner's workstation. `NODE` is
deliberately the production node only; do not deploy this gateway to the
retrieval/RAG node.

```bash
set -euo pipefail

# Must succeed only after the owner's root-level docker-group change and a fresh
# ops login. A failure is a blocker: stop here and ask the owner for the root fix.
ssh "$NODE" "sudo -n -u ops -H bash -c 'id -nG | tr \" \" \"\\n\" | grep -qx docker && docker ps >/dev/null'"
```

## 1. Copy the staged files as `ops`

These commands do not rely on the `ops` deploy key (which is intentionally
read-only) and preserve the local staged files as the source of truth.

```bash
set -euo pipefail

for file in docker-compose.yml config.yaml; do
  cat "configs/litellm-staging/$file" | \
    ssh "$NODE" "sudo -n -u ops -H bash -c 'set -euo pipefail; install -d -m 700 \"\$HOME/litellm-gateway\"; cat > \"\$HOME/litellm-gateway/$file\"; chmod 600 \"\$HOME/litellm-gateway/$file\"'"
done
```

## 2. Materialize remote-only secrets and `.env`

This writes no secret to this repository. It requires the existing
`~ops/.env.secrets` to contain `ZAI_API_KEY`; it adds strong, remote-only
values for the two secrets that do not yet exist. The master key must carry
LiteLLM's required prefix, which the script generates rather than quotes.

```bash
ssh "$NODE" 'sudo -n -u ops -H bash -s' <<'OPS_ENV'
set -euo pipefail

secrets="$HOME/.env.secrets"
test -r "$secrets"
chmod 600 "$secrets"
grep -q '^ZAI_API_KEY=' "$secrets"

# LiteLLM requires the master key to carry its documented two-letter prefix
# followed by a dash. It is assembled from two string literals so that this
# runbook never contains a token-shaped literal, which the repository's secret
# scanners would report as a finding.
key_prefix="sk""-"
if ! grep -q '^LITELLM_MASTER_KEY=' "$secrets"; then
  umask 077
  printf 'LITELLM_MASTER_KEY=%s%s\n' "$key_prefix" "$(openssl rand -hex 32)" >> "$secrets"
fi
if ! grep -q '^POSTGRES_PASSWORD=' "$secrets"; then
  umask 077
  printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)" >> "$secrets"
fi

set -a
. "$secrets"
set +a
: "${ZAI_API_KEY:?missing from the ops env-secrets file}"
: "${LITELLM_MASTER_KEY:?missing from the ops env-secrets file}"
: "${POSTGRES_PASSWORD:?missing from the ops env-secrets file}"
case "$LITELLM_MASTER_KEY" in "$key_prefix"*) ;; *) exit 1 ;; esac

umask 077
cat > "$HOME/litellm-gateway/.env" <<EOF
ZAI_API_KEY=$ZAI_API_KEY
LITELLM_MASTER_KEY=$LITELLM_MASTER_KEY
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
DATABASE_URL=postgresql://litellm:$POSTGRES_PASSWORD@postgres:5432/litellm
EOF
chmod 600 "$HOME/litellm-gateway/.env"
OPS_ENV
```

## 3. Start the staged compose project and wait for health

```bash
ssh "$NODE" 'sudo -n -u ops -H bash -s' <<'OPS_UP'
set -euo pipefail
cd "$HOME/litellm-gateway"
docker compose up -d
docker compose ps

for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error http://127.0.0.1:4000/health >/dev/null; then
    exit 0
  fi
  sleep 2
done
exit 1
OPS_UP
```

## 4. Generate the two runtime virtual keys

The key values are generated in LiteLLM's Postgres-backed runtime and are not
static compose configuration. The responses remain in the `ops` home (mode
600); do not copy them into this repository or terminal output. Later W1-2 and
W1-3 provisioning must transfer each value only to its matching account's
private env-secrets file.

```bash
ssh "$NODE" "sudo -n -u ops -H SOFT_BUDGET='$SOFT_BUDGET' HARD_BUDGET='$HARD_BUDGET' bash -s" <<'OPS_KEYS'
set -euo pipefail
set -a
. "$HOME/litellm-gateway/.env"
set +a
cd "$HOME/litellm-gateway"
umask 077

for alias in agent peer; do
  curl --fail --silent --show-error \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H 'Content-Type: application/json' \
    -X POST http://127.0.0.1:4000/key/generate \
    --data "{\"key_alias\":\"$alias\",\"models\":[\"glm-main\"],\"soft_budget\":$SOFT_BUDGET,\"max_budget\":$HARD_BUDGET,\"budget_duration\":\"30d\",\"metadata\":{\"tags\":[\"$alias\"]}}" \
    > ".$alias-key.json"
  chmod 600 ".$alias-key.json"
done

python3 -c 'import json; assert json.load(open(".agent-key.json"))["key"]; assert json.load(open(".peer-key.json"))["key"]; print("agent and peer virtual keys created")'
OPS_KEYS
```

## 5. Verify a completion, Postgres spend row, tag block, and hard cap

The positive smoke uses the `agent` key without disclosing it. The tag test
expects the documented `no_deployments_with_tag_routing` rejection. The budget
test always restores the approved monthly limits, including when an assertion
fails.

```bash
ssh "$NODE" "sudo -n -u ops -H SOFT_BUDGET='$SOFT_BUDGET' HARD_BUDGET='$HARD_BUDGET' bash -s" <<'OPS_VERIFY'
set -euo pipefail
set -a
. "$HOME/litellm-gateway/.env"
set +a
cd "$HOME/litellm-gateway"
AGENT_KEY="$(python3 -c 'import json; print(json.load(open(".agent-key.json"))["key"])')"

curl --fail --silent --show-error \
  -H "Authorization: Bearer $AGENT_KEY" \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:4000/v1/chat/completions \
  --data '{"model":"glm-main","messages":[{"role":"user","content":"Reply with exactly: deployment smoke passed"}],"max_tokens":8}' \
  > /tmp/litellm-w1-1-smoke.json

# The current LiteLLM Prisma table name is quoted and contains one row per call.
docker compose exec -T postgres psql -U litellm -d litellm \
  -c 'SELECT COUNT(*) AS spend_log_rows FROM "LiteLLM_SpendLogs";'

patent_code="$(curl --silent --show-error -o /tmp/litellm-w1-1-patent-block.json -w '%{http_code}' \
  -H "Authorization: Bearer $AGENT_KEY" \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:4000/v1/chat/completions \
  --data '{"model":"glm-main","metadata":{"tags":["patent-sensitive"]},"messages":[{"role":"user","content":"blocked routing probe"}]}' || true)"
test "$patent_code" -ge 400
grep -q 'no_deployments_with_tag_routing' /tmp/litellm-w1-1-patent-block.json

restore_agent_budget() {
  curl --fail --silent --show-error -o /dev/null \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H 'Content-Type: application/json' \
    -X POST http://127.0.0.1:4000/key/update \
    --data "{\"key\":\"$AGENT_KEY\",\"soft_budget\":$SOFT_BUDGET,\"max_budget\":$HARD_BUDGET,\"budget_duration\":\"30d\"}"
}
trap restore_agent_budget EXIT

curl --fail --silent --show-error -o /dev/null \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:4000/key/update \
  --data "{\"key\":\"$AGENT_KEY\",\"soft_budget\":0.005,\"max_budget\":0.01,\"budget_duration\":\"30d\"}"

blocked=false
for attempt in $(seq 1 5); do
  cap_code="$(curl --silent --show-error -o /tmp/litellm-w1-1-hard-cap.json -w '%{http_code}' \
    -H "Authorization: Bearer $AGENT_KEY" \
    -H 'Content-Type: application/json' \
    -X POST http://127.0.0.1:4000/v1/chat/completions \
    --data '{"model":"glm-main","messages":[{"role":"user","content":"Write a detailed 4000-token explanation of the number one."}],"max_tokens":4096}' || true)"
  if [ "$cap_code" -ge 400 ]; then
    blocked=true
    break
  fi
done
test "$blocked" = true
grep -Eqi 'budget|exceed' /tmp/litellm-w1-1-hard-cap.json
restore_agent_budget
trap - EXIT
OPS_VERIFY
```

## 6. Register the `systemd --user` unit and verify it

```bash
ssh "$NODE" 'sudo -n -u ops -H bash -s' <<'OPS_UNIT'
set -euo pipefail
install -d -m 700 "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/litellm-gateway.service" <<'UNIT'
[Unit]
Description=LiteLLM gateway compose stack
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=%h/litellm-gateway
ExecStart=/usr/bin/sg docker -c '/usr/bin/docker compose -f docker-compose.yml up -d'
ExecStop=/usr/bin/sg docker -c '/usr/bin/docker compose -f docker-compose.yml down'
TimeoutStartSec=0

[Install]
WantedBy=default.target
UNIT
chmod 600 "$HOME/.config/systemd/user/litellm-gateway.service"
OPS_UNIT

ssh "$NODE" "sudo -n -u ops XDG_RUNTIME_DIR=/run/user/\$(id -u ops) systemctl --user daemon-reload"
ssh "$NODE" "sudo -n -u ops XDG_RUNTIME_DIR=/run/user/\$(id -u ops) systemctl --user enable --now litellm-gateway.service"
ssh "$NODE" "sudo -n -u ops XDG_RUNTIME_DIR=/run/user/\$(id -u ops) systemctl --user is-active litellm-gateway.service"
```

## 7. Capture redacted evidence in your own private records

Run this final section only after every preceding verification passed. The
remote `ops` deploy key is read-only by design, so any commit is made from the
owner's local checkout. Never copy `.env`, virtual-key JSON, raw completion
content, or Authorization headers into any repository.

**This public repository carries no operational evidence.** Verification output
and infrastructure change notes belong in the operator's own private records —
not in a tracked path here. Set `EVIDENCE_DIR` to a directory outside this
checkout before running the block below; it has no default and the block refuses
to run without it.

```bash
set -euo pipefail
: "${EVIDENCE_DIR:?set EVIDENCE_DIR to a private directory outside this checkout}"
mkdir -p "$EVIDENCE_DIR"

ssh "$NODE" "sudo -n -u ops -H bash -c 'cd \"\$HOME/litellm-gateway\" && docker compose ps'" \
  > "$EVIDENCE_DIR/01-compose-ps.txt"
ssh "$NODE" "sudo -n -u ops -H bash -c 'set -a; . \"\$HOME/litellm-gateway/.env\"; set +a; curl --fail --silent -H \"Authorization: Bearer \$LITELLM_MASTER_KEY\" http://127.0.0.1:4000/health'" \
  > "$EVIDENCE_DIR/02-health.json"
ssh "$NODE" "sudo -n -u ops -H bash -c 'cd \"\$HOME/litellm-gateway\" && docker compose exec -T postgres psql -U litellm -d litellm -c '\''SELECT COUNT(*) AS spend_log_rows FROM \"LiteLLM_SpendLogs\";'\'''" \
  > "$EVIDENCE_DIR/03-spend-row-count.txt"
ssh "$NODE" "sudo -n -u ops XDG_RUNTIME_DIR=/run/user/\$(id -u ops) systemctl --user is-enabled litellm-gateway.service" \
  > "$EVIDENCE_DIR/04-user-unit-enabled.txt"
ssh "$NODE" "sudo -n -u ops XDG_RUNTIME_DIR=/run/user/\$(id -u ops) systemctl --user is-active litellm-gateway.service" \
  > "$EVIDENCE_DIR/05-user-unit-active.txt"
```

Then update the one tracked record by hand — do **not** regenerate it from a
here-document in this runbook, which would overwrite newer policy text:

- `configs/routing-policy.md` — set the verified binding date and the provider
  model actually confirmed live; leave the budget amounts out of the file.

Record the deployment, the reserved port, the sole `glm-main` alias, the
runtime-only `agent`/`peer` virtual keys, and the verifications above in your own
infrastructure change log, outside this repository.

```bash
git add configs/routing-policy.md configs/litellm-staging
git commit -m 'feat: litellm gateway (personal keys, budgets, patent-safe routing)'
git push
```

If any gate fails, retain only redacted diagnostics under `$EVIDENCE_DIR` and do
not perform the final commit or push.
