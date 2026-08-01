#!/usr/bin/env python3
"""Produce an independent peer-bot attestation from the peer sandbox copy.

SI-6: the peer replies BESIDE the deploy request, so its attestation must land on
the same declared supply-chain surface. The channel is either handed in by the
pipeline (``--channel-id``) or resolved once in :func:`main` through the shared
directory under the kind ``SKILL_ATTEST`` — this module resolves nothing itself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from automation import config_env  # noqa: E402
from automation.peer_attestation import PEER_ATTESTATION_TTL, _DIGEST, _NONCE, _SKILL, format_attestation, parse_attestation, parse_timestamp  # noqa: E402
from automation.skill_review import _frontmatter_passes, _scenario_passes, _secret_scan_passes, skill_digest  # noqa: E402

API = "https://discord.com/api/v10"
OPS_REPO_ROOT = Path("/nonexistent-deploy-root")
RELEASES_ROOT = Path("/nonexistent-release-store")
RELEASE_CURRENT = Path("/nonexistent-release-current")
GATE_DIR = Path("~/.hermes/skill-gate").expanduser()
INTEROP_CONFIG = Path("~/.hermes/interop/config.json").expanduser()
USER_AGENT = "DiscordBot (https://github.com/orientpine/autophagy-agents, 0)"
_VERIFIER_FILES = ("automation/peer_attest.py", "automation/peer_attestation.py", "automation/skill_review.py")


@dataclass(frozen=True, slots=True)
class AttestRequest:
    skill: str
    staged_dir: Path
    expected_digest: str
    request_message_id: str
    deploy_nonce: str
    channel_id: str
    refresh: bool = False


@dataclass(frozen=True, slots=True)
class AttestResult:
    exit_code: int
    digest: str
    verdict: str


@dataclass(frozen=True, slots=True)
class AttestationAttempt:
    request: AttestRequest
    digest: str
    verdict: str
    now: datetime


def _find_tamperable_path(repo_root: Path) -> Path | None:
    """Return the first checkout path a non-owner could tamper with (fail-closed on stat errors)."""
    for path in (repo_root, *(repo_root / rel for rel in _VERIFIER_FILES)):
        try:
            mode = path.stat().st_mode
        except OSError:
            return path
        if mode & 0o022:
            return path
    return None


def _is_trusted_attestor_root(
    repo_root: Path,
    *,
    ops_repo_root: Path = OPS_REPO_ROOT,
    releases_root: Path = RELEASES_ROOT,
    release_current: Path = RELEASE_CURRENT,
) -> bool:
    """True only for the mirror, a DIRECT release child, or realpath(current).

    ``Path(__file__).resolve()`` follows the ``current`` symlink, so a runtime
    launched from ``/srv/autophagy-agent-current`` sees REPO_ROOT as
    ``/srv/autophagy-agent-releases/<sha>``. Trust exactly those three shapes and
    nothing deeper: the releases parent itself and any grandchild are refused."""
    if repo_root == ops_repo_root:
        return True
    try:
        resolved_current = release_current.resolve()
    except OSError:
        resolved_current = release_current
    if repo_root == resolved_current and repo_root.parent == releases_root:
        return True
    return repo_root.parent == releases_root and repo_root != releases_root


def _configured_runtime_roots() -> tuple[Path, Path, Path]:
    ops_root = config_env.deploy_root()
    parent = ops_root.parent
    return (
        ops_root,
        parent / "autophagy-agent-releases",
        parent / "autophagy-agent-current",
    )


class DiscordTransport(Protocol):
    """What attesting needs of Discord — reading the thread and replying into it.

    Resolving a channel is deliberately absent: only the shared directory may, and
    :func:`main` has already bound one before ``attest`` ever runs.
    """

    def replies_after(self, channel_id: str, message_id: str) -> Sequence[Mapping[str, Any]]: ...

    def post_reply(self, channel_id: str, message_id: str, content: str) -> None: ...


@dataclass(frozen=True, slots=True)
class DiscordRestTransport:
    token: str

    def replies_after(self, channel_id: str, message_id: str) -> Sequence[Mapping[str, Any]]:
        messages = self.api("GET", f"/channels/{channel_id}/messages?after={message_id}&limit=100")
        return messages if isinstance(messages, list) else ()

    def post_reply(self, channel_id: str, message_id: str, content: str) -> None:
        payload = {
            "content": content,
            "message_reference": {"message_id": message_id, "channel_id": channel_id, "fail_if_not_exists": True},
            "allowed_mentions": {"replied_user": False},
        }
        self.api("POST", f"/channels/{channel_id}/messages", payload)

    def api(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        request = Request(
            f"{API}{path}",
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bot {self.token}", "Content-Type": "application/json", "User-Agent": USER_AGENT},
            method=method,
        )
        with urlopen(request, timeout=30) as response:  # noqa: S310
            body = response.read().decode("utf-8")
        return json.loads(body) if body else None


def _already_attested(transport: DiscordTransport, attempt: AttestationAttempt) -> bool:
    """Return true if a reusable peer reply already carries this exact binding."""
    request = attempt.request
    for message in transport.replies_after(request.channel_id, request.request_message_id):
        reference = message.get("message_reference")
        content = message.get("content")
        if not isinstance(reference, Mapping) or not isinstance(content, str):
            continue
        if reference.get("message_id") != request.request_message_id:
            continue
        attestation = parse_attestation(content)
        if attestation is None:
            continue
        if not (
            attestation.request == request.deploy_nonce
            and attestation.skill == request.skill
            and attestation.digest == attempt.digest
        ):
            continue
        if not request.refresh:
            return True
        timestamp = message.get("timestamp")
        attested_at = parse_timestamp(timestamp) if isinstance(timestamp, str) else None
        if (
            attested_at is not None
            and attestation.verdict == attempt.verdict
            and attested_at <= attempt.now <= attested_at + PEER_ATTESTATION_TTL
        ):
            return True
    return False


def attest(
    request: AttestRequest,
    transport: DiscordTransport,
    now: datetime | None = None,
) -> AttestResult:
    """Review the peer sandbox bytes and publish exactly one bound verdict reply."""
    try:
        digest = skill_digest(request.staged_dir)
    except OSError:
        return AttestResult(1, "unavailable", "FAIL")
    checks = (
        _frontmatter_passes(request.staged_dir, request.skill),
        _scenario_passes(request.staged_dir, None),
        _secret_scan_passes(request.staged_dir),
        digest == request.expected_digest,
    )
    verdict = "PASS" if all(checks) else "FAIL"
    body = format_attestation(request.deploy_nonce, request.skill, digest, verdict)
    attempt = AttestationAttempt(request, digest, verdict, now or datetime.now(UTC))
    try:
        if _already_attested(transport, attempt):
            return AttestResult(0 if verdict == "PASS" else 1, digest, verdict)
        transport.post_reply(request.channel_id, request.request_message_id, body)
    except (HTTPError, OSError, json.JSONDecodeError):
        return AttestResult(1, digest, "FAIL")
    return AttestResult(0 if verdict == "PASS" else 1, digest, verdict)


def _attest_channel_id(transport: DiscordRestTransport) -> str:
    """SI-6: ask the shared directory where a ``SKILL_ATTEST`` reply belongs — never a DM.

    The resolver is imported HERE, not at module scope, so the attestor still boots from
    the four stdlib-only files its tamper guard covers; a resolver it cannot reach refuses
    the run instead of guessing a channel.
    """
    try:
        from automation import skill_gate_surface
        from automation.interop.approval_surface import ApprovalKind, ApprovalSurfaceError
    except ImportError as error:
        raise OSError("approval surface resolver unavailable; pass --channel-id") from error
    identity = skill_gate_surface.GateIdentity(transport.token, transport.api, GATE_DIR, INTEROP_CONFIG)
    try:
        return skill_gate_surface.surface_for(ApprovalKind.SKILL_ATTEST, identity).new().channel_id
    except ApprovalSurfaceError as error:
        raise OSError(f"peer attestation surface unresolved: {error}") from error


def _parse_request(argv: Sequence[str]) -> AttestRequest | None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", required=True)
    parser.add_argument("--staged-dir", required=True)
    parser.add_argument("--hash", required=True)
    parser.add_argument("--request-message-id", required=True)
    parser.add_argument("--deploy-nonce", required=True)
    parser.add_argument("--channel-id", default="")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    if _SKILL.fullmatch(args.skill) is None or _DIGEST.fullmatch(args.hash) is None or _NONCE.fullmatch(args.deploy_nonce) is None:
        return None
    return AttestRequest(
        args.skill,
        Path(args.staged_dir),
        args.hash,
        args.request_message_id,
        args.deploy_nonce,
        args.channel_id,
        bool(args.refresh),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run only from the protected ops checkout with peer's own bot token."""
    tamperable = _find_tamperable_path(REPO_ROOT)
    if tamperable is not None:
        print(f"FATAL: peer attestor checkout is group/other-writable: {tamperable}", file=sys.stderr)
        return 2
    try:
        ops_root, releases_root, release_current = _configured_runtime_roots()
    except config_env.ConfigError as error:
        print(f"FATAL: peer attestor runtime configuration unavailable: {error}", file=sys.stderr)
        return 2
    if not _is_trusted_attestor_root(
        REPO_ROOT,
        ops_repo_root=ops_root,
        releases_root=releases_root,
        release_current=release_current,
    ):
        print(f"FATAL: peer attestor must run from the release runtime or {ops_root}", file=sys.stderr)
        return 2
    request = _parse_request(sys.argv[1:] if argv is None else argv)
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if request is None or not token:
        print("FATAL: invalid attestation arguments or missing Discord token", file=sys.stderr)
        return 2
    transport = DiscordRestTransport(token)
    try:
        bound = replace(request, channel_id=request.channel_id or _attest_channel_id(transport))
    except OSError as error:
        print(f"FATAL: {error}", file=sys.stderr)
        return 2
    result = attest(bound, transport)
    print(f"PEER-ATTEST-{result.verdict} skill={request.skill} sha256={result.digest}")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
