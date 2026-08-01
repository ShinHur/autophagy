"""Peer registry: agent_id <-> Discord bot user id mapping from configs/peers.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from typing import Any

SUPPORTED_VERSION = 1


def _scalar(text: str) -> Any:
    """Read one constrained YAML scalar: a quoted string, an integer, or bare text."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text.isdigit():
        return int(text)
    return text


def _fallback_document(raw: str) -> dict[str, Any]:
    """Parse the constrained peers shape when PyYAML is not installed.

    This mirrors the sibling rule loaders under ``skills/``: PyYAML is an
    optional dependency, so a checkout that has installed nothing must still be
    able to read the one document shape this file documents. Only that shape is
    understood — anything else produces a structure the strict validation below
    rejects, so an unreadable file fails closed rather than loading as empty.
    """
    document: dict[str, Any] = {}
    peers: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    in_peers = False
    for line in raw.splitlines():
        content = line.split("#", 1)[0].rstrip()
        if not content.strip():
            continue
        indent = len(content) - len(content.lstrip())
        value = content.strip()
        if indent == 0:
            in_peers = value == "peers:"
            current = None
            if not in_peers and ":" in value:
                key, _, scalar = value.partition(":")
                document[key.strip()] = _scalar(scalar.strip())
            continue
        if not in_peers:
            continue
        if indent == 2 and value.endswith(":"):
            current = {}
            peers[value[:-1].strip()] = current
        elif indent == 4 and current is not None and ":" in value:
            key, _, scalar = value.partition(":")
            current[key.strip()] = _scalar(scalar.strip())
    document["peers"] = peers
    return document


def _parse_document(text: str, path: Path) -> Any:
    try:
        import yaml  # noqa: PLC0415
    except ModuleNotFoundError:
        return _fallback_document(text)
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise RegistryError(f"cannot read peers file {path}: {error}") from error


class RegistryError(ValueError):
    """The peers file is missing, malformed, or has an unsupported version."""


@dataclass(frozen=True, slots=True)
class Peer:
    """One registered team agent."""

    agent_id: str
    bot_user_id: str
    bot_name: str


@dataclass(frozen=True, slots=True)
class PeerRegistry:
    """Immutable lookup table over the registered peers."""

    peers: tuple[Peer, ...]

    def agent_id_for(self, bot_user_id: str) -> str | None:
        """Return the registered agent_id for a Discord bot user id, if any."""
        for peer in self.peers:
            if peer.bot_user_id == bot_user_id:
                return peer.agent_id
        return None


def load_registry(path: Path) -> PeerRegistry:
    """Parse and strictly validate the peers.yaml registry."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RegistryError(f"cannot read peers file {path}: {error}") from error
    raw = _parse_document(text, path)
    if not isinstance(raw, dict) or raw.get("version") != SUPPORTED_VERSION:
        raise RegistryError(f"peers file {path} must declare version: {SUPPORTED_VERSION}")
    peers_node = raw.get("peers")
    if not isinstance(peers_node, dict) or not peers_node:
        raise RegistryError(f"peers file {path} must define a non-empty peers mapping")
    peers: list[Peer] = []
    for agent_id, entry in peers_node.items():
        if not isinstance(agent_id, str) or not agent_id:
            raise RegistryError(f"peers file {path}: agent_id keys must be non-empty strings")
        if not isinstance(entry, dict):
            raise RegistryError(f"peers file {path}: peer {agent_id} must be a mapping")
        bot_user_id = entry.get("bot_user_id")
        bot_name = entry.get("bot_name")
        if not isinstance(bot_user_id, str) or not bot_user_id.isdigit():
            raise RegistryError(f"peers file {path}: peer {agent_id} needs a numeric string bot_user_id")
        if not isinstance(bot_name, str) or not bot_name:
            raise RegistryError(f"peers file {path}: peer {agent_id} needs a non-empty bot_name")
        peers.append(Peer(agent_id=agent_id, bot_user_id=bot_user_id, bot_name=bot_name))
    ids = [peer.bot_user_id for peer in peers]
    if len(ids) != len(set(ids)):
        raise RegistryError(f"peers file {path}: duplicate bot_user_id entries")
    return PeerRegistry(peers=tuple(peers))
