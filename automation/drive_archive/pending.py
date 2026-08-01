"""Pending batch JSON records for drive-archive approvals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from automation.drive_archive.manifest import FileEntry
from automation.interop.external_effect_gate import JsonValue
from automation.interop.approval_lifecycle import ApprovalRecordsError


class PendingRecordError(RuntimeError):
    detail: str

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class PendingBatch:
    """A digest awaiting the owner's bound ✅/⛔ reaction."""

    action_hash: str
    target_id: str
    message_id: str
    project: str
    created_at: str
    files: tuple[FileEntry, ...]
    kind: str = ""
    surface: str = ""
    channel_id: str = ""
    policy_version: int = 0

    @property
    def is_bound(self) -> bool:
        """A pre-binding record names no surface; its channel drains as legacy."""
        return bool(self.surface) and bool(self.channel_id)

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "action_hash": self.action_hash,
            "target_id": self.target_id,
            "message_id": self.message_id,
            "project": self.project,
            "created_at": self.created_at,
            "files": [{"path": entry.path, "sha256": entry.sha256} for entry in self.files],
            "kind": self.kind,
            "surface": self.surface,
            "channel_id": self.channel_id,
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_json(cls, data: dict[str, JsonValue]) -> PendingBatch:
        raw_files = data["files"]
        if not isinstance(raw_files, list):
            raise PendingRecordError("pending record has malformed files")
        files = tuple(
            FileEntry(str(item["path"]), str(item["sha256"]))
            for item in raw_files
            if isinstance(item, dict)
        )
        return cls(
            action_hash=str(data["action_hash"]),
            target_id=str(data["target_id"]),
            message_id=str(data["message_id"]),
            project=str(data["project"]),
            created_at=str(data["created_at"]),
            files=files,
            kind=str(data.get("kind", "")),
            surface=str(data.get("surface", "")),
            channel_id=str(data.get("channel_id", "")),
            policy_version=int(data.get("policy_version", 0) or 0),
        )


def _slug(action_hash: str) -> str:
    return action_hash.replace(":", "_").replace("/", "_")


@dataclass(frozen=True, slots=True)
class PendingBatchStore:
    root: Path

    def _record(self, action_hash: str) -> Path:
        return self.root / f"{_slug(action_hash)}.json"

    def put(self, pending: PendingBatch) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        record = self._record(pending.action_hash)
        record.write_text(
            json.dumps(pending.to_json(), ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        record.chmod(0o600)

    def get(self, action_hash: str) -> PendingBatch | None:
        try:
            data = json.loads(self._record(action_hash).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            return PendingBatch.from_json(data)
        except (KeyError, PendingRecordError):
            return None

    def all(self) -> tuple[PendingBatch, ...]:
        if not self.root.exists():
            return ()
        found: list[PendingBatch] = []
        for record in sorted(self.root.glob("*.json")):
            try:
                found.append(PendingBatch.from_json(json.loads(record.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, KeyError, PendingRecordError):
                continue
        return tuple(found)

    def all_strict(self) -> tuple[PendingBatch, ...]:
        if not self.root.exists():
            return ()
        found: list[PendingBatch] = []
        for record in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(record.read_text(encoding="utf-8"))
                found.append(PendingBatch.from_json(data))
            except (OSError, json.JSONDecodeError, KeyError, PendingRecordError, TypeError) as error:
                raise ApprovalRecordsError(str(record)) from error
        return tuple(found)

    def drop(self, pending: PendingBatch) -> None:
        expected = (pending.action_hash, pending.message_id, pending.project)
        for record in sorted(self.root.glob("*.json")):
            try:
                data = json.loads(record.read_text(encoding="utf-8"))
                current = PendingBatch.from_json(data)
            except (OSError, json.JSONDecodeError, KeyError, PendingRecordError, TypeError):
                continue
            actual = (current.action_hash, current.message_id, current.project)
            if actual == expected:
                record.unlink(missing_ok=True)
                return

    def remove(self, action_hash: str) -> None:
        self._record(action_hash).unlink(missing_ok=True)
