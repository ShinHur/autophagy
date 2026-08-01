"""Managed skill channel tag fetcher (MS-S3) — read-only git over a pre-approved remote.

Syncs the managed-skills feed into a local mirror and lists release tags
(``<skill>/v<sequence>``, Codified decision 3). Fail-closed: any git failure
raises :class:`ManagedFetchError` with the git stderr. The remote URL comes
ONLY from the injected config (pre-approved remote — never a CLI or function
argument), the mirror's push URL is disabled on every sync pass (obsidian
SI-5 precedent — never write back to a read-only feed), and fetch NEVER
prunes local tags (decision 16: upstream tag deletion is not revocation).
Every subprocess call carries an explicit ``env=`` (watcher-cron 규약 b-2).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

_GIT_TIMEOUT_SECONDS: Final = 120.0
_GIT_CLONE_TIMEOUT_SECONDS: Final = 600.0
_TAG_SEQUENCE_PATTERN: Final = re.compile(r"v([1-9]\d*)\Z")
_LOGGER: Final = logging.getLogger(__name__)


class GitRunner(Protocol):
    def __call__(
        self,
        args: list[str],
        /,
        *,
        env: dict[str, str],
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]: ...


class FetchConfig(Protocol):
    """Structural contract for the sync config (MS-S6 builds the concrete object)."""

    @property
    def remote_url(self) -> str: ...
    @property
    def mirror_dir(self) -> Path: ...
    @property
    def ssh_key_path(self) -> Path: ...


class ManagedFetchError(Exception):
    """Read-only sync of the managed-skills mirror failed; retry next tick."""


@dataclass(frozen=True, slots=True)
class FetchResult:
    mirror_dir: Path
    fetched: bool
    cloned: bool


@dataclass(frozen=True, slots=True)
class ReleaseTag:
    skill: str
    sequence: int
    tag_name: str


@dataclass(frozen=True, slots=True)
class _Git:
    runner: GitRunner
    environment: dict[str, str]

    def run(
        self,
        args: tuple[str, ...],
        timeout: float = _GIT_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = self.runner(
                list(args),
                env=self.environment,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ManagedFetchError(f"git step failed: {' '.join(args)}: {error}") from error
        if result.returncode != 0:
            raise ManagedFetchError(
                f"git step returned {result.returncode}: {' '.join(args)}: {result.stderr}"
            )
        return result


def _ssh_environment(ssh_key_path: Path) -> dict[str, str]:
    environment = dict(os.environ)
    environment["GIT_SSH_COMMAND"] = f"ssh -i {ssh_key_path} -o IdentitiesOnly=yes"
    return environment


def _disable_push_args(mirror_dir: Path) -> tuple[str, ...]:
    return ("git", "-C", str(mirror_dir), "remote", "set-url", "--push", "origin", "DISABLED")


def sync_remote(config: FetchConfig, runner: GitRunner = subprocess.run) -> FetchResult:
    """Clone (mirror absent) or tag-fetch (mirror present) the pre-approved remote."""
    git = _Git(runner=runner, environment=_ssh_environment(config.ssh_key_path))
    mirror_dir = config.mirror_dir
    if (mirror_dir / ".git").is_dir():
        # No --prune: decision 16 — upstream tag deletion is NOT revocation.
        _ = git.run(("git", "-C", str(mirror_dir), "fetch", "origin", "+refs/tags/*:refs/tags/*"))
        # SI-5 hardening is idempotent here: an interrupted clone may have left
        # the push URL enabled, so re-disable it on every fetch pass too.
        _ = git.run(_disable_push_args(mirror_dir))
        return FetchResult(mirror_dir=mirror_dir, fetched=True, cloned=False)

    mirror_dir.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    mirror_dir.parent.chmod(0o700)
    _ = git.run(
        ("git", "clone", config.remote_url, str(mirror_dir)),
        timeout=_GIT_CLONE_TIMEOUT_SECONDS,
    )
    _ = git.run(_disable_push_args(mirror_dir))
    return FetchResult(mirror_dir=mirror_dir, fetched=False, cloned=True)


def _parse_release_tag(skill: str, tag_name: str) -> ReleaseTag | None:
    prefix = f"{skill}/"
    if not tag_name.startswith(prefix):
        return None
    match = _TAG_SEQUENCE_PATTERN.fullmatch(tag_name.removeprefix(prefix))
    if match is None:
        return None
    return ReleaseTag(skill=skill, sequence=int(match.group(1)), tag_name=tag_name)


def list_release_tags(
    mirror: Path,
    skill: str,
    runner: GitRunner = subprocess.run,
) -> tuple[ReleaseTag, ...]:
    """Return ``<skill>/v<seq>`` release tags, sequence-sorted ascending (numeric).

    Malformed tag names are skipped (and reported once) — a malformed tag is
    not fatal; only the git invocation failing is.
    """
    git = _Git(runner=runner, environment=dict(os.environ))
    result = git.run(("git", "-C", str(mirror), "tag", "--list", f"{skill}/v*"))
    tags: list[ReleaseTag] = []
    malformed = 0
    for line in result.stdout.splitlines():
        tag_name = line.strip()
        if not tag_name:
            continue
        tag = _parse_release_tag(skill, tag_name)
        if tag is None:
            malformed += 1
            continue
        tags.append(tag)
    if malformed:
        _LOGGER.warning("skipped %d malformed release tag(s) for skill %s", malformed, skill)
    return tuple(sorted(tags, key=lambda tag: tag.sequence))
