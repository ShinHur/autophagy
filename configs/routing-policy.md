# LiteLLM routing policy

> Deployment-specific values (provider API keys, virtual-key material, the
> monthly budget amounts, and node/host names) are **not** recorded here. They
> live in the private environment file on the gateway host. This document is the
> source of truth for the *policy shape* only.

## Current binding

- Verified binding date: 2026-07-16.
- The sole LiteLLM alias is `glm-main`, bound to provider model `zai/glm-5.2`.
- `glm-main` is the only gateway alias. Anthropic aliases remain deferred, and OpenAI uses Hermes OAuth outside LiteLLM.
- The deployment is tagged `default` and `non-patent-sensitive`; tag filtering remains enabled.

## Agent primary model (2026-07-22)

- The Hermes agent's primary conversational model is `openai-codex/gpt-5.6-sol`
  (ChatGPT subscription OAuth, outside LiteLLM) with `agent.reasoning_effort: high`.
- `glm-main` remains the sole gateway alias and now serves as the agent's
  FALLBACK (rate-limit/overload/connection failover) and the batch pipelines
  (mail triage, meeting, twin_distill, report, …).

## Virtual-key budget policy

- Runtime-only virtual keys: `agent` and `peer`.
- Each key is restricted to `glm-main` and carries a monthly soft-alert budget
  and a hard cap over a `30d` `budget_duration`. Choose both amounts for your own
  deployment and set them at `/key/generate` time; they are intentionally not
  recorded in this repository.
- `fail_closed_budget_enforcement: true` is enabled. Budget alerts are forwarded by the private dispatcher; no key material or webhook address is stored in this repository.

## Patent-sensitive requests

Callers must include `metadata.tags=["patent-sensitive"]` for sensitive work. The deployed `PatentSensitiveGlmBlocker` rejects a `glm-main` request carrying that tag with HTTP 403 and the `no_deployments_with_tag_routing` marker before a provider call. Hermes must route the work to a non-GLM path instead.

Fallback-window guard (2026-07-22): the recall skill releases patent-sensitive content into a conversation only when the agent's primary model route is verified non-GLM, and prefixes each released row with the `[[PATENT-SENSITIVE-RECALL]]` sentinel. The same pre-call guard also rejects any `glm-main` request whose message payload carries that sentinel, so a mid-conversation failover to `glm-main` cannot leak recall-released patent content to the GLM provider.

The configured LiteLLM tag filter remains a deployment-selection control. The pre-call guard is the verified fail-closed enforcement point for the current single-deployment `main-stable` gateway and preserves the intended no-deployment rejection semantics.

## Rebinding procedure

1. Confirm the replacement provider model through a live provider check and record the model ID and verification date here.
2. Change only `model_list[glm-main]` in `configs/litellm-staging/config.yaml`; preserve the non-sensitive deployment tags, tag guard, key budgets, and alias name.
3. Copy only the non-secret staged configuration to the gateway account's `litellm-gateway/` directory and run `docker compose up -d --force-recreate litellm`. Do not remove the Postgres volume or regenerate virtual keys.
4. Verify authenticated `/health`, one redacted `glm-main` completion with a spend-row increase, the patent-tag HTTP rejection marker, and a temporary near-zero hard-cap rejection followed by restoration of the deployment's approved soft/hard limits (`30d`).
5. Retain the masked verification evidence and the infrastructure change record in the operator's own private records — this public repository deliberately carries no operational evidence — and push the configuration commit before treating the rebinding as complete.
