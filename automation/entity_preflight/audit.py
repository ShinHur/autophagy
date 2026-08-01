"""PII-safe audit helpers for entity preflight."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .contracts import JsonValue, PreflightDecision

DEFAULT_AUDIT_ROOT = "~/.hermes/entity-preflight/audit"
DEFAULT_OPERATIONAL_ROOT = "~/.hermes/entity-preflight/operational"


def input_sha256(raw_text: str) -> str:
    return "sha256:" + hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def operational_event(decision: PreflightDecision) -> dict[str, JsonValue]:
    """Return the only representation allowed in general operational logs.

    Raw text, mention surfaces, relationship questions, normalized/display
    values, source references, resource ids, and candidate ids are omitted.
    """
    source_counts: dict[str, int] = {}
    for candidate in decision.candidates:
        source_counts[candidate.source.value] = source_counts.get(candidate.source.value, 0) + 1
    entity_types = sorted({entity.entity_kind.value for entity in decision.request.entities})
    return {
        "event": "entity_preflight_decision",
        "correlation_id": decision.audit.correlation_id,
        "policy_version": decision.audit.policy_version,
        "target_system": decision.request.target_system,
        "operation": decision.request.operation,
        "entity_count": len(decision.request.entities),
        "entity_types": cast(JsonValue, entity_types),
        "candidate_count": len(decision.candidates),
        "candidate_sources": cast(JsonValue, source_counts),
        "selected_count": len(decision.selected),
        "decision": decision.decision.value,
        "reason": decision.reason.value,
        "needs_confirmation": decision.needs_confirmation,
        "input_sha256": decision.audit.input_sha256,
    }


class PrivateJsonlAuditStore:
    """Append full sensitive records under a mode-700 root and mode-600 file."""

    def __init__(self, root: str | Path = DEFAULT_AUDIT_ROOT) -> None:
        self.root = Path(root).expanduser()

    def append(self, event: Mapping[str, JsonValue]) -> str:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        path = self.root / "entity-preflight.jsonl"
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        file_descriptor = os.open(path, flags, 0o600)
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.write(json.dumps(dict(event), ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return str(path)


class JsonlOperationalLog:
    """Durable general log for the redacted preflight events and quality records.

    It is a separate root from the sensitive store so that retention and access
    can differ, and it reuses the same hardened writer because these records are
    still personal-adjacent operational metadata.
    """

    def __init__(self, root: str | Path = DEFAULT_OPERATIONAL_ROOT) -> None:
        self._store = PrivateJsonlAuditStore(root)

    def emit(self, event: Mapping[str, JsonValue]) -> None:
        self._store.append(event)
