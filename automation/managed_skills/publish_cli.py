"""Gate-verified publisher for immutable managed-skill git releases."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, TypeAlias, TypeGuard

from automation import config_env
from automation.managed_skills.manifest import (
    MANAGED_PREFIX,
    MAX_SKILL_NAME,
    ManifestError,
    ManagedManifest,
    canonical_json,
    manifest_digest,
    parse_manifest,
)
from automation.managed_skills.announce import announce_release_from_environment
from automation.skill_review import skill_digest


_EVIDENCE: Final = re.compile(r"(?P<message_id>[^:\s]+):(?P<nonce>[0-9a-f]{32})\Z")
_RELEASE_TAG: Final = re.compile(r"v(?P<sequence>[1-9]\d*)\Z")
JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


class PublishError(Exception): ...


@dataclass(frozen=True, slots=True)
class PublishConfig:
    skill: str
    managed_repo: Path
    skills_src: Path
    changelog_file: Path
    signing_key: Path
    approve_evidence: str | None
    injection_file: Path | None
    stage_publish_request: bool = False
    publish_evidence: str | None = None
    discord_token_file: Path | None = None


class Runner(Protocol):
    def __call__(self, args: list[str], /, *, env: dict[str, str], capture_output: bool, text: bool, timeout: float) -> subprocess.CompletedProcess[str]: ...


def _is_json_object(value: object) -> TypeGuard[dict[str, JsonValue]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


@dataclass(frozen=True, slots=True)
class _Process:
    runner: Runner
    environment: dict[str, str]

    def run(self, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        try:
            return self.runner(
                list(args),
                env=self.environment,
                capture_output=True,
                text=True,
                timeout=120.0,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise PublishError(f"subprocess failed: {' '.join(args)}: {error}") from error

    def require(self, args: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        result = self.run(args)
        if result.returncode != 0:
            raise PublishError(f"subprocess returned {result.returncode}: {' '.join(args)}")
        return result


def _approval_evidence(config: PublishConfig, process: _Process) -> None:
    if config.approve_evidence is not None:
        if _EVIDENCE.fullmatch(config.approve_evidence) is None:
            raise PublishError("approve evidence must be MESSAGE_ID:DEPLOY_NONCE")
        return
    deployment_process = _Process(process.runner, {**process.environment, "SKILL_SRC_DIR": str(config.skills_src)})
    result = deployment_process.require(
        (str(Path(__file__).resolve().parents[2] / "automation" / "deploy-skill.sh"), config.skill, "--approve-only")
    )
    if sum(_EVIDENCE.fullmatch(line) is not None for line in result.stdout.splitlines()) != 1:
        raise PublishError("approve-only did not emit exactly one MESSAGE_ID:DEPLOY_NONCE line")


def _preconditions(config: PublishConfig, environment: Mapping[str, str]) -> None:
    if config.stage_publish_request and config.publish_evidence is not None:
        raise PublishError("stage-publish-request and publish-evidence are mutually exclusive")
    if "DISCORD_BOT_TOKEN" in environment:
        raise PublishError("publisher refuses agent-runtime environment")
    if not config.skill.startswith(MANAGED_PREFIX) or len(config.skill) > MAX_SKILL_NAME:
        raise PublishError("skill must use the managed prefix and fit the name limit")
    if not config.managed_repo.is_dir():
        raise PublishError(f"managed repository missing: {config.managed_repo}")
    if not (config.skills_src / "SKILL.md").is_file():
        raise PublishError(f"skill source missing SKILL.md: {config.skills_src}")
    if not config.signing_key.is_file():
        raise PublishError(f"signing key path is not a file: {config.signing_key}")
    if config.skills_src.resolve().is_relative_to(config.managed_repo.resolve()):
        raise PublishError("source tree must not be inside the managed repository")
    if any(path.is_symlink() for path in config.skills_src.rglob("*")):
        raise PublishError("source tree contains a symlink")


def _release_state(config: PublishConfig, process: _Process) -> tuple[int, str | None]:
    tags = process.require(
        ("git", "-C", str(config.managed_repo), "tag", "--list", f"{config.skill}/v*")
    ).stdout.splitlines()
    releases = [
        (int(match.group("sequence")), tag)
        for tag in tags
        if (match := _RELEASE_TAG.fullmatch(tag.removeprefix(f"{config.skill}/"))) is not None
    ]
    if not releases:
        return 1, None
    sequence, tag = max(releases)
    previous = parse_manifest(
        process.require(
            ("git", "-C", str(config.managed_repo), "show", f"{tag}:manifests/{config.skill}.json")
        ).stdout
    )
    if previous.skill != config.skill or previous.release_sequence != sequence:
        raise PublishError("previous release tag and manifest disagree")
    return sequence + 1, previous.skill_sha256


def _source_commit(config: PublishConfig, process: _Process) -> str | None:
    result = process.run(("git", "-C", str(config.skills_src.parent.parent), "rev-parse", "HEAD"))
    return result.stdout.strip() if result.returncode == 0 else None


def _manifest(config: PublishConfig, process: _Process) -> ManagedManifest:
    sequence, previous_sha256 = _release_state(config, process)
    try:
        changelog_raw: object = json.loads(config.changelog_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PublishError(f"changelog file is unreadable JSON: {config.changelog_file}") from error
    if not _is_json_object(changelog_raw):
        raise PublishError("changelog file must contain a JSON object")
    changelog = changelog_raw
    allowed = {"changelog", "breaking", "compatibility", "migration", "revoked_digests"}
    missing = {"changelog", "breaking", "compatibility"} - set(changelog)
    if set(changelog) - allowed or missing:
        raise PublishError("changelog file has unknown or missing release fields")
    payload: dict[str, JsonValue] = {
        "schema_version": 1,
        "publisher": config_env.require_env(
            "MANAGED_PUBLISHER",
            hint="Set the managed-skill publisher principal",
        ),
        "skill": config.skill,
        "release_sequence": sequence,
        "source_commit": _source_commit(config, process),
        "skill_sha256": skill_digest(config.skills_src),
        "previous_sha256": previous_sha256,
        "changelog": changelog["changelog"],
        "breaking": changelog["breaking"],
        "compatibility": changelog["compatibility"],
        "migration": changelog.get("migration"),
        "revoked_digests": changelog.get("revoked_digests", []),
    }
    return parse_manifest(json.dumps(payload))


def _publish_approval(
    config: PublishConfig, manifest: ManagedManifest, process: _Process
) -> bool:
    tag = f"{config.skill}/v{manifest.release_sequence}"
    digest = manifest_digest(manifest)
    if config.publish_evidence is not None:
        evidence = _EVIDENCE.fullmatch(config.publish_evidence)
        if evidence is None:
            raise PublishError("publish evidence must be MESSAGE_ID:PUBLISH_NONCE")
        message_id, nonce = evidence.group("message_id"), evidence.group("nonce")
    else:
        request = process.require((sys.executable, "-m", "automation.skill_gate", "publish-request", "--skill", config.skill, "--hash", manifest.skill_sha256, "--manifest-hash", digest, "--tag", tag, "--json"))
        try:
            response_raw: object = json.loads(request.stdout)
        except json.JSONDecodeError as error:
            raise PublishError("publish-request did not return JSON") from error
        if not _is_json_object(response_raw):
            raise PublishError("publish-request returned a non-object response")
        message_id, nonce = response_raw.get("message_id"), response_raw.get("publish_nonce")
        if not isinstance(message_id, str) or not message_id or not isinstance(nonce, str) or not _EVIDENCE.fullmatch(f"x:{nonce}"):
            raise PublishError("publish-request returned invalid approval binding")
    if config.stage_publish_request:
        print(f"PUBLISH-STAGED message_id={message_id} publish_nonce={nonce} skill_sha256={manifest.skill_sha256} manifest_sha256={digest} tag={tag}")
        return True
    check = (sys.executable, "-m", "automation.skill_gate", "publish-check", "--skill", config.skill, "--hash", manifest.skill_sha256, "--manifest-hash", digest, "--tag", tag, "--message-id", message_id, "--publish-nonce", nonce)
    if config.injection_file is not None:
        check += ("--injection-file", str(config.injection_file))
    _ = process.require(check)
    return False


def publish(
    config: PublishConfig,
    runner: Runner = subprocess.run,
    environment: Mapping[str, str] | None = None,
) -> ManagedManifest:
    active_environment = dict(os.environ if environment is None else environment)
    _preconditions(config, active_environment)
    subprocess_environment = dict(active_environment)
    if config.discord_token_file is not None:
        try:
            token = config.discord_token_file.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise PublishError(f"discord token file unreadable: {config.discord_token_file}") from error
        if not token:
            raise PublishError("discord token file is empty")
        subprocess_environment["DISCORD_BOT_TOKEN"] = token
    process = _Process(runner, subprocess_environment)
    _approval_evidence(config, process)
    status = process.require(("git", "-C", str(config.managed_repo), "status", "--porcelain"))
    if status.stdout:
        raise PublishError("managed repository worktree must be clean before publish approval")
    manifest = _manifest(config, process)
    if _publish_approval(config, manifest, process):
        return manifest
    destination = config.managed_repo / "skills" / config.skill
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(config.skills_src, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    manifest_path = config.managed_repo / "manifests" / f"{config.skill}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _ = manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
    tag = f"{config.skill}/v{manifest.release_sequence}"
    message = f"Publish {tag}\nmanifest_sha256:{manifest_digest(manifest)}"
    _ = process.require(("git", "-C", str(config.managed_repo), "add", f"skills/{config.skill}", f"manifests/{config.skill}.json"))
    _ = process.require(("git", "-C", str(config.managed_repo), "commit", "-m", f"Publish {tag}"))
    publisher_email = config_env.require_env(
        "MANAGED_PUBLISHER_EMAIL",
        validator=config_env.is_email,
        hint="Set the signing identity email for managed-skill releases",
    )
    _ = process.require(("git", "-C", str(config.managed_repo), "-c", "gpg.format=ssh", "-c", f"user.signingkey={config.signing_key}", "-c", f"user.email={publisher_email}", "tag", "-s", tag, "-m", message))
    _ = process.require(("git", "-C", str(config.managed_repo), "push"))
    _ = process.require(("git", "-C", str(config.managed_repo), "push", "origin", tag))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--skill", required=True)
    _ = parser.add_argument("--managed-repo", type=Path, required=True)
    for option in ("--skills-src", "--changelog-file", "--signing-key", "--injection-file", "--discord-token-file"):
        _ = parser.add_argument(option, type=Path)
    _ = parser.add_argument("--approve-evidence")
    mode = parser.add_mutually_exclusive_group()
    _ = mode.add_argument("--stage-publish-request", action="store_true")
    _ = mode.add_argument("--publish-evidence")
    args = parser.parse_args()
    source = args.skills_src or Path(__file__).resolve().parents[2] / "skills" / args.skill
    changelog = args.changelog_file
    signing_key = args.signing_key or (Path(value) if (value := os.environ.get("MANAGED_SIGNING_KEY")) else None)
    if changelog is None or signing_key is None:
        print("PUBLISH-BLOCK: --changelog-file and signing key are required", file=sys.stderr)
        return 2
    try:
        manifest = publish(
            PublishConfig(args.skill, args.managed_repo, source, changelog, signing_key, args.approve_evidence, args.injection_file, args.stage_publish_request, args.publish_evidence, args.discord_token_file)
        )
    except (ManifestError, PublishError) as error:
        print(f"PUBLISH-BLOCK: {error}", file=sys.stderr)
        return 1
    if args.stage_publish_request:
        return 0
    print(f"PUBLISHED skill={manifest.skill} tag={manifest.skill}/v{manifest.release_sequence}")
    _ = announce_release_from_environment(manifest, f"{manifest.skill}/v{manifest.release_sequence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
