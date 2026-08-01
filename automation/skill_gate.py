#!/usr/bin/env python3
"""Owner-only Discord approval gate for skill deployment (W1-8).

Runs as the ``agent`` account on the production node. The production approval path
is a manual reaction by the guild owner on the surface this flow DECLARES —
``SKILL_DEPLOY`` / ``MANAGED_ACTIVATE``, resolved through the shared directory by
:mod:`automation.skill_gate_surface` and pinned there forever by SI-6.
For unattended regression only, a signed injected approval is accepted under
``E2E_TEST_MODE=1`` by reusing the W1-6 interop injection adapter (HMAC).
The production agent gateway independently refuses E2E_TEST_MODE at boot.

Exit codes: 0 approved / request ok; 1 approval absent or invalid (and a
refused/failed record retirement); 2 usage/config error; 3 weekly auto-proposal
rate limit exceeded; 6 approval-lifecycle refusal (an existing live request is
preserved).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

INTEROP_RUNTIME = Path(os.environ.get("INTEROP_RUNTIME", "~/.hermes/interop_runtime")).expanduser()
sys.path.insert(0, str(INTEROP_RUNTIME))

from automation.peer_attestation import AttestationExpectation, load_bot_ids, parse_timestamp as _parse_timestamp, valid_peer_attestation  # noqa: E402
from automation.skill_gate_e2e import GateBindings, check_injected, sign  # noqa: E402
from automation.skill_gate_review import review_status_line  # noqa: E402
from automation import skill_gate_approval, skill_gate_request, skill_gate_retire, skill_gate_specs, skill_gate_surface  # noqa: E402
from automation.interop.approval_lifecycle import ApprovalRequest  # noqa: E402
from automation.interop.approval_surface import ApprovalKind, ApprovalSurfaceError  # noqa: E402

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/orientpine/autophagy-agents, 0)"
APPROVE_EMOJI = skill_gate_specs.APPROVE_EMOJI  # ✅ WHITE HEAVY CHECK MARK
GATE_DIR = Path("~/.hermes/skill-gate").expanduser()
INTEROP_CONFIG = Path("~/.hermes/interop/config.json").expanduser()
APPROVAL_LOG = Path(os.environ.get("APPROVAL_LOG_PATH", "/srv/autophagy-agents/logs/approvals.jsonl"))
OPS_PEERS_CONFIG = Path("/srv/autophagy-agents/configs/peers.yaml")
WEEKLY_AUTO_LIMIT = 3
_REQUEST_BINDING = re.compile(
    r"\A\[skill-deploy\] 승인 요청\n- skill: `(?P<skill>[a-z0-9][a-z0-9-]{1,40})`\n"
    r"- sha256: `(?P<digest>[0-9a-f]{64})`\n- deploy_nonce: `(?P<nonce>[0-9a-f]{32})`\n"
)

_mask = skill_gate_specs.mask
provenance_lines = skill_gate_specs.provenance_lines  # deploy 요청 CLI 표면 재노출


def _token() -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        print("FATAL: DISCORD_BOT_TOKEN missing", file=sys.stderr)
        raise SystemExit(2)
    return token


def _api(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    request = Request(
        f"{API}{path}",
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bot {_token()}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method=method,
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310
        body = response.read().decode("utf-8")
    return json.loads(body) if body else None


def _owner_id() -> str:
    try:
        owner = json.loads(INTEROP_CONFIG.read_text(encoding="utf-8")).get("owner_id")
    except OSError:
        print(f"FATAL: interop config unreadable: {INTEROP_CONFIG}", file=sys.stderr)
        raise SystemExit(2) from None
    if not isinstance(owner, str) or not owner:
        print("FATAL: owner_id missing from interop config", file=sys.stderr)
        raise SystemExit(2)
    return owner


def _identity() -> skill_gate_surface.GateIdentity:
    """This process's bot identity — the shared directory resolves the surface from it."""
    return skill_gate_surface.GateIdentity(_token(), _api, GATE_DIR, INTEROP_CONFIG)


def _deploy_bindings(skill: str) -> skill_gate_surface.SupplyChainSurface:
    """Declare which supply-chain kind this run authorizes; the directory answers where."""
    return skill_gate_surface.surface_for(skill_gate_surface.deploy_kind(skill), _identity())


def _approval_text(skill: str, digest: str, message_id: str) -> str:
    return f"APPROVE skill:{skill} sha256:{digest} msg:{message_id}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    path.chmod(0o600)


def _log_approval(
    args: argparse.Namespace,
    method: str,
    execution: skill_gate_approval.ApprovalExecution | None = None,
) -> None:
    payload = {
        "action": "skill.deploy",
        "approval": {"channel": "approvals", "message_id": args.message_id, "method": method},
        "payload": {"skill_sha256": args.hash},
        "target_id": f"skill:{args.skill}",
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    record = {
        "action": "skill.deploy",
        "approval": payload["approval"],
        "hash": f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}",
        "result": {"status": "approved"},
        "target_id": f"skill:{args.skill}",
        "timestamp": _utc_now(),
    }
    if execution is not None:
        record["binding"] = {
            "action": execution.action,
            "action_hash": execution.request.action_hash,
            "deploy_nonce": execution.nonce,
            "destination": execution.destination,
            "message_id": execution.request.message_id,
        }
    _append_jsonl(APPROVAL_LOG, record)


def _deploy_gate(args: argparse.Namespace) -> skill_gate_approval.SkillApprovalGate:
    """This run's deploy gate: a fresh nonce, plus one action hash over what ✅ authorizes."""
    spec = skill_gate_specs.DeploySpec(
        skill=args.skill,
        digest=args.hash,
        deploy_nonce=str(getattr(args, "deploy_nonce", "")) or secrets.token_hex(16),
        review_status=review_status_line(GATE_DIR / "review-verdicts.jsonl", args.skill, args.hash),
        provenance=skill_gate_specs.provenance_of(str(getattr(args, "provenance_file", ""))),
        binding=_REQUEST_BINDING,
    )
    surface = skill_gate_approval.GateSurface(
        _api, GATE_DIR, _owner_id, lambda: _deploy_bindings(args.skill)
    )
    return skill_gate_approval.SkillApprovalGate(surface, spec)


def _approval_execution(
    gate: skill_gate_approval.SkillApprovalGate, args: argparse.Namespace
) -> skill_gate_approval.ApprovalExecution:
    request = ApprovalRequest(
        key=gate.spec.key(),
        action_hash=gate.spec.action_hash(),
        message_id=args.message_id,
        channel_id=gate.channel_id(),
        created_at="",
    )
    return skill_gate_approval.ApprovalExecution(
        request=request,
        nonce=args.deploy_nonce,
        action="skill.deploy",
        destination=f"skill:{args.skill}",
    )


def _auto_proposals_exhausted(proposals: Path, week: str) -> bool:
    if not proposals.exists():
        return False
    rows = [json.loads(line) for line in proposals.read_text(encoding="utf-8").splitlines() if line]
    used = sum(1 for row in rows if row.get("week") == week and row.get("source") == "auto")
    if used < WEEKLY_AUTO_LIMIT:
        return False
    print(f"RATE-LIMIT: {used} auto proposals already this week (max {WEEKLY_AUTO_LIMIT})", file=sys.stderr)
    return True


def cmd_request(args: argparse.Namespace) -> int:
    """One live request per skill: reuse it, supersede it with --fresh, or refuse."""
    json_output = bool(getattr(args, "json", False))
    gate = _deploy_gate(args)
    reused = skill_gate_request.reuse(gate)
    if reused is not None and not args.fresh:
        return skill_gate_request.emit(reused, json_output=json_output)
    source = os.environ.get("SKILL_PROPOSAL_SOURCE", "manual")
    proposals = GATE_DIR / "proposals.jsonl"
    week = datetime.now(timezone.utc).strftime("%G-W%V")
    if source == "auto" and _auto_proposals_exhausted(proposals, week):
        return 3
    requested = skill_gate_request.post_request(gate, fresh=bool(args.fresh))
    record = requested.record
    if requested.posted and record is not None:
        _append_jsonl(proposals, {"hash": args.hash, "message_id": record["message_id"],
                                  "skill": args.skill, "source": source,
                                  "timestamp": _utc_now(), "week": week})
    return skill_gate_request.emit(requested, json_output=json_output)


def _peer_attestation_present(args: argparse.Namespace, channel_id: str) -> bool:
    bot_ids = load_bot_ids(OPS_PEERS_CONFIG)
    request = _api("GET", f"/channels/{channel_id}/messages/{args.message_id}")
    author = request.get("author") if isinstance(request, dict) else None
    content = request.get("content") if isinstance(request, dict) else None
    timestamp = request.get("timestamp") if isinstance(request, dict) else None
    matched = _REQUEST_BINDING.match(content) if isinstance(content, str) else None
    requested_at = _parse_timestamp(timestamp) if isinstance(timestamp, str) else None
    if bot_ids is None or not isinstance(author, dict) or matched is None or requested_at is None:
        return False
    if author.get("id") != bot_ids.agent_bot_id or author.get("bot") is not True:
        return False
    if matched.group("skill") != args.skill or matched.group("digest") != args.hash or matched.group("nonce") != args.deploy_nonce:
        return False
    messages = _api("GET", f"/channels/{channel_id}/messages?after={args.message_id}&limit=100")
    if not isinstance(messages, list):
        return False
    expectation = AttestationExpectation(channel_id, args.message_id, args.deploy_nonce, args.skill, args.hash, requested_at)
    return valid_peer_attestation(messages, expectation, bot_ids, _now())


def _owner_approval_present(args: argparse.Namespace, owner_id: str, channel_id: str) -> bool:
    try:
        users = _api(
            "GET",
            f"/channels/{channel_id}/messages/{args.message_id}/reactions/"
            f"{quote(APPROVE_EMOJI)}?limit=100",
        )
    except HTTPError as error:
        if error.code != 404:
            raise
        users = []
    if not isinstance(users, list):
        users = []
    for user in users:
        if not isinstance(user, dict):
            continue
        user_id, is_bot = str(user.get("id", "")), bool(user.get("bot", False))
        if user_id == owner_id and not is_bot:
            return True
        print(f"IGNORED non-owner reaction: user={_mask(user_id)} bot={is_bot}", file=sys.stderr)
    print(
        f"REJECTED: no owner {APPROVE_EMOJI} reaction on message {_mask(args.message_id)}",
        file=sys.stderr,
    )
    return False


def cmd_check(args: argparse.Namespace) -> int:
    owner_id = _owner_id()
    gate = _deploy_gate(args)
    execution = _approval_execution(gate, args)
    channel_id = execution.request.channel_id
    if not _peer_attestation_present(args, channel_id):
        print("REJECTED: valid peer attestation absent", file=sys.stderr)
        return 1
    bindings = GateBindings(
        owner_id,
        channel_id,
        _approval_text,
        lambda _skill, _digest, _message_id, method: _log_approval(args, method, execution),
        _mask,
    )
    if args.injection_file:
        if os.environ.get("E2E_TEST_MODE") != "1":
            print("REJECTED: injected approval requires E2E_TEST_MODE=1", file=sys.stderr)
            return 1
        if not gate.valid_binding(execution, APPROVAL_LOG):
            print("REJECTED: approval execution binding invalid", file=sys.stderr)
            return 1
        return check_injected(args, bindings)
    if os.environ.get("E2E_TEST_MODE"):
        print("FATAL: E2E_TEST_MODE set but no --injection-file; refusing ambiguous mode", file=sys.stderr)
        return 2
    if not _owner_approval_present(args, owner_id, channel_id):
        return 1
    if not gate.valid_approval(execution, APPROVAL_LOG):
        print("REJECTED: owner approval binding invalid", file=sys.stderr)
        return 1
    _log_approval(args, "manual_reaction", execution)
    print(f"APPROVED method=manual_reaction owner={_mask(owner_id)}")
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    bindings = GateBindings(
        _owner_id(),
        _deploy_gate(args).channel_id(),
        _approval_text,
        lambda _skill, _digest, _message_id, method: _log_approval(args, method),
        _mask,
    )
    return sign(args, bindings)


def cmd_consume(args: argparse.Namespace) -> int:
    """Retire the decision this deploy's MOUNT consumed — CAS on (skill, hash, message id)."""
    return skill_gate_retire.emit(skill_gate_retire.consume(_deploy_gate(args), args.message_id))


def cmd_abandon(args: argparse.Namespace) -> int:
    """Operator override: audited retirement of a decision whose effect can never run."""
    order = skill_gate_retire.AbandonOrder(args.message_id, args.reason, skill_gate_retire.actor())
    audit = skill_gate_retire.abandon_log(APPROVAL_LOG)
    return skill_gate_retire.emit(skill_gate_retire.abandon(_deploy_gate(args), order, audit))


def main() -> int:
    where = skill_gate_surface.where_to_look(ApprovalKind.SKILL_DEPLOY)
    parser = argparse.ArgumentParser(description=f"{__doc__}\n{where}")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("request", cmd_request), ("check", cmd_check), ("sign", cmd_sign),
                       ("consume", cmd_consume), ("abandon", cmd_abandon)):
        cmd = sub.add_parser(name)
        cmd.add_argument("--skill", required=True)
        cmd.add_argument("--hash", required=True)
        cmd.set_defaults(func=func)
        if name == "request":
            cmd.add_argument("--fresh", action="store_true")
            cmd.add_argument("--json", action="store_true")
            cmd.add_argument("--provenance-file", default="")
        else:
            cmd.add_argument("--message-id", required=True)
        if name == "check":
            cmd.add_argument("--injection-file", default="")
            cmd.add_argument("--deploy-nonce", required=True)
            cmd.add_argument("--provenance-file", default="")
        if name == "abandon":
            cmd.add_argument("--reason", required=True)
        if name == "sign":
            cmd.add_argument("--out", required=True)
            cmd.add_argument("--user-id", default="")
            cmd.add_argument("--forge-signature", action="store_true")
    try:  # publish subcommands only resolve on the workstation (full repo); the staged agent gate omits skill_gate_publish
        from automation.skill_gate_publish import cmd_publish_check, cmd_publish_request  # local import: avoids module cycle
    except ModuleNotFoundError:
        pass
    else:
        for name, func in (("publish-request", cmd_publish_request), ("publish-check", cmd_publish_check)):
            cmd = sub.add_parser(name)
            cmd.add_argument("--skill", required=True)
            cmd.add_argument("--hash", required=True)
            cmd.add_argument("--manifest-hash", required=True)
            cmd.add_argument("--tag", required=True)
            cmd.set_defaults(func=func)
            if name == "publish-request":
                cmd.add_argument("--json", action="store_true")
            else:
                cmd.add_argument("--message-id", required=True)
                cmd.add_argument("--publish-nonce", required=True)
                cmd.add_argument("--injection-file", default="")
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except ApprovalSurfaceError as error:
        print(f"FATAL: approval surface unresolved ({error}); pin deploy_approvals_channel_id in interop config", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
