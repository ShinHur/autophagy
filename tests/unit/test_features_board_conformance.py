from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS = _REPO_ROOT / "docs"
_FEATURES = _DOCS / "features.md"
_INTRO_DIR = _DOCS / "기능소개"
_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _local_target(raw: str) -> Path | None:
    candidate = raw.strip().split("#", 1)[0]
    if not candidate or candidate.startswith(("http://", "https://")):
        return None
    if candidate.startswith("docs/"):
        return _REPO_ROOT / candidate
    return (_DOCS / candidate).resolve()


def test_feature_inventory_keeps_public_sections_in_order() -> None:
    text = _FEATURES.read_text(encoding="utf-8")
    headers = (
        text.index("## 포함"),
        text.index("## 의도적으로 제외"),
        text.index("## 기능 소개"),
    )
    assert headers == tuple(sorted(headers))


def test_feature_inventory_local_links_resolve_in_public_checkout() -> None:
    missing = sorted(
        raw
        for raw in _LINK.findall(_FEATURES.read_text(encoding="utf-8"))
        if (target := _local_target(raw)) is not None and not target.exists()
    )
    assert not missing, f"features.md links missing public artifacts: {missing}"


def test_feature_inventory_intro_links_target_intro_documents() -> None:
    intro_links = sorted(
        target
        for raw in _LINK.findall(_FEATURES.read_text(encoding="utf-8"))
        if (target := _local_target(raw)) is not None and target.parent == _INTRO_DIR
    )
    assert intro_links, "features.md must link at least one public feature introduction"
    assert all(target.suffix == ".md" and target.is_file() for target in intro_links)
