from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Protocol

from automation.managed_skills.manifest import ManagedManifest


_LOGGER = logging.getLogger(__name__)
_MAX_EXCERPT = 120
_URLISH = re.compile(r"https?://\S+|git@\S+|\b[\w.-]+\.git\b", re.IGNORECASE)
_TOKENISH = re.compile(r"\b(?:sk-[A-Za-z0-9_-]+|ghp_[A-Za-z0-9_-]+)\b")
_PEMISH = re.compile(r"-----BEGIN[^\n]*-----|-----END[^\n]*-----")


class AnnounceTransport(Protocol):
    def send(self, body: str) -> object: ...


@dataclass(frozen=True, slots=True)
class AnnounceResult:
    sent: bool


def _excerpt(text: str) -> str:
    cleaned = " ".join(text.split())
    cleaned = _URLISH.sub("[redacted]", cleaned)
    cleaned = _TOKENISH.sub("[redacted]", cleaned)
    cleaned = _PEMISH.sub("[redacted]", cleaned)
    if len(cleaned) <= _MAX_EXCERPT:
        return cleaned
    return f"{cleaned[: _MAX_EXCERPT - 1].rstrip()}…"


def _render(manifest: ManagedManifest, tag: str) -> str:
    breaking = "⚠ BREAKING" if manifest.breaking else "breaking=false"
    excerpt = _excerpt(manifest.changelog) or "(no changelog excerpt)"
    return "\n".join(
        (
            f"skill={manifest.skill}",
            f"tag={tag}",
            f"digest={manifest.skill_sha256[:12]}",
            f"breaking={breaking}",
            f"delta={excerpt}",
            "note=publisher-node canary 진행 중",
        )
    )


def announce_release(
    manifest: ManagedManifest,
    tag: str,
    *,
    transport: AnnounceTransport,
    channel_id: str | None,
) -> AnnounceResult:
    if not channel_id:
        _LOGGER.info("managed release announce skipped: missing channel_id")
        return AnnounceResult(sent=False)
    body = _render(manifest, tag)
    try:
        _ = transport.send(body)
    except Exception:
        _LOGGER.exception("managed release announce failed")
        return AnnounceResult(sent=False)
    return AnnounceResult(sent=True)


def announce_release_from_environment(manifest: ManagedManifest, tag: str) -> AnnounceResult:
    channel_id = os.environ.get("MANAGED_ANNOUNCE_CHANNEL_ID")
    token = os.environ.get("MANAGED_ANNOUNCE_BOT_TOKEN")
    if not channel_id or not token:
        return AnnounceResult(sent=False)
    try:
        from automation.interop.discord_transport import DiscordTransport

        return announce_release(
            manifest,
            tag,
            transport=DiscordTransport(token, channel_id),
            channel_id=channel_id,
        )
    except Exception:
        return AnnounceResult(sent=False)
