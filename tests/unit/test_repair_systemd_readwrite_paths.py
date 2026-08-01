"""The repair units must not hold write access to the deploy checkout.

Rollout ② of 「수리 반영 경로 규칙」: the deploy checkout
is a one-way mirror, so the repair units must not be able to write into it.
Removing it from `ReadWritePaths` is what actually ENFORCES the work-clone
migration — without this, a regression could silently start committing there
again (which is exactly how the drift recovered on 2026-07-28/29 was produced).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

_SYSTEMD: Final = Path(__file__).resolve().parents[2] / "automation" / "repair" / "systemd"
_DEPLOY_CHECKOUT: Final = "%%AUTOPHAGY_DEPLOY_ROOT%%"
_WORK_CLONE: Final = "%%AUTOPHAGY_REPAIR_WORK_ROOT%%"
_UNITS: Final = (
    "autophagy-repair-agent.service",
    "autophagy-repair-approval-watch.service",
)


def _read_write_paths(unit: str) -> list[str]:
    text = (_SYSTEMD / unit).read_text(encoding="utf-8")
    match = re.search(r"^ReadWritePaths=(.*)$", text, re.MULTILINE)
    assert match is not None, f"{unit} has no ReadWritePaths line"
    return match.group(1).split()


@pytest.mark.parametrize("unit", _UNITS)
def test_unit_when_declaring_writable_paths_then_excludes_deploy_checkout(unit: str) -> None:
    assert _DEPLOY_CHECKOUT not in _read_write_paths(unit), (
        f"{unit} still grants write access to the deploy checkout; "
        "the repair agent could resume producing unpushable drift there"
    )


@pytest.mark.parametrize("unit", _UNITS)
def test_unit_when_declaring_writable_paths_then_includes_work_clone(unit: str) -> None:
    assert _WORK_CLONE in _read_write_paths(unit), (
        f"{unit} cannot write the repair work clone; apply would fail closed"
    )
