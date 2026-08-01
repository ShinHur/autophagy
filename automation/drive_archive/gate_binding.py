"""Bridge a batch manifest to the production external-effect approval gate.

The whole point of this module: the batch's ``action_hash`` and approval check
come from ``automation.interop.external_effect_gate`` unchanged, so one owner
✅ authorizes exactly one manifest and nothing else.
"""

from __future__ import annotations

import os
from pathlib import Path

from automation.drive_archive import config, manifest, paths
from automation.interop.external_effect_gate import (
    ApprovalContext,
    ExternalEffectDecision,
    ToolCall,
    evaluate_tool_call,
    load_denylist,
)

TOOL_NAME = "drive_archive.batch_upload"


def denylist_path() -> Path:
    override = os.environ.get("DRIVE_ARCHIVE_DENYLIST")
    if override:
        return Path(override).expanduser()
    return paths.repo_root() / "configs" / "external-effect-tools.yaml"


def build_tool_call(batch: manifest.BatchManifest) -> ToolCall:
    return ToolCall(tool_name=TOOL_NAME, arguments=batch.to_arguments())


def approval_context() -> ApprovalContext:
    return ApprovalContext(
        approval_log=paths.approval_log(),
        owner_id=config.owner_id(),
        e2e_test_mode=os.environ.get("E2E_TEST_MODE") == "1",
    )


def evaluate(
    batch: manifest.BatchManifest, *, context: ApprovalContext | None = None
) -> ExternalEffectDecision:
    ctx = context if context is not None else approval_context()
    return evaluate_tool_call(build_tool_call(batch), load_denylist(denylist_path()), ctx)
