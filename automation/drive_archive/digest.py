"""Pure render of the batch-approval digest the owner reacts to.

The action_hash is embedded literally (header + footer) so the reaction watcher
can content-bind the owner's ✅/⛔ to exactly this batch. The batch always uploads
ALL files — the approval binds to the action_hash over the full manifest, never to
the visible body. With 361 files the raw path list was an 1859-char wall that
stopped being an approval-decision surface (owner feedback 2026-07-25), so above
the list limit the body aggregates by archive class instead.

The owner-facing reaction line is rendered by ``approval_surface`` rather than
phrased here, so every flow asks for a decision in the same words. It names no
surface: the approval message says how to answer, never where it lives.
"""

from __future__ import annotations

from dataclasses import dataclass

from automation.drive_archive.manifest import BatchManifest, FileEntry
from automation.drive_archive.routing import ARCHIVE_CLASSES, classify
from automation.interop.approval_surface import (
    ApprovalKind,
    reaction_instruction,
    required_surface,
)

_MAX_CONTENT = 1900  # Discord's hard limit is 2000; keep headroom for CJK/emoji width
_LIST_LIMIT = 12  # owner-approved: at or below this the raw path list is still the useful view
_MAX_LABEL = 80  # project/root name come from env — bound their share of the message
_PLAN_COMMAND = "python3 -m automation.drive_archive.sync_cli plan"
_KIND = ApprovalKind.DRIVE_ARCHIVE


@dataclass(frozen=True, slots=True)
class DigestRequest:
    """Everything the digest renders from. Pure data: no disk, env, or clock access."""

    manifest: BatchManifest
    action_hash: str
    root_name: str
    tracked: frozenset[str]


def _label(value: str) -> str:
    if len(value) <= _MAX_LABEL:
        return value
    return value[: _MAX_LABEL - 1] + "…"


def _class_counts(entries: tuple[FileEntry, ...]) -> list[tuple[str, int]]:
    counts = dict.fromkeys(ARCHIVE_CLASSES, 0)
    for entry in entries:
        counts[classify(entry.path)] += 1
    present = [(name, count) for name, count in counts.items() if count]
    return sorted(present, key=lambda item: (-item[1], ARCHIVE_CLASSES.index(item[0])))


def _paths_body(entries: tuple[FileEntry, ...], budget: int) -> list[str]:
    body: list[str] = []
    used = 0
    for entry in entries:
        line = f"- `{entry.path}` → `{classify(entry.path)}/`  ({entry.sha256[:12]})"
        overflow = f"\n- …외 {len(entries) - len(body)}건"
        if used + len(line) + 1 + len(overflow) > budget:
            break
        body.append(line)
        used += len(line) + 1
    if len(body) < len(entries):
        body.append(f"- …외 {len(entries) - len(body)}건")
    return body


def _classes_body(entries: tuple[FileEntry, ...]) -> list[str]:
    return [
        "분류별 집계",
        *[f"- `{name}/` {count}건" for name, count in _class_counts(entries)],
        "",
        f"전체 목록: `{_PLAN_COMMAND}`",
    ]


def render(request: DigestRequest) -> str:
    ordered: tuple[FileEntry, ...] = tuple(sorted(request.manifest.files, key=lambda e: e.path))
    added = sum(1 for entry in ordered if entry.path not in request.tracked)
    updated = len(ordered) - added
    header = [
        f"📥 Drive 아카이브 동기화 요청 — 프로젝트 `{_label(request.manifest.project)}`",
        f"대상 파일 {len(ordered)}건 · 신규 {added} · 변경 {updated} · action_hash `{request.action_hash}`",
        f"대상 폴더 `{_label(request.root_name)}` (내 Drive · 분류별 하위폴더 자동 생성)",
        "",
    ]
    instruction = reaction_instruction(_KIND, required_surface(_KIND))
    footer = [
        "",
        f"{instruction}  (✅ = {len(ordered)}건 전체 업로드 · hash `{request.action_hash}`)",
    ]
    budget = _MAX_CONTENT - len("\n".join([*header, *footer]))
    body = _paths_body(ordered, budget) if len(ordered) <= _LIST_LIMIT else _classes_body(ordered)
    return "\n".join([*header, *body, *footer])
