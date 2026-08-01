from __future__ import annotations

from typing import Final

from repo_scan_models import Rule


_DIRECT_CLAIMS: Final[tuple[str, ...]] = (
    r"production[- ]ready",
    r"arbitrary institutional mail",
    r"site backend included",
    r"multi-node HA",
    r"end-to-end tested",
    r"stdlib[- ]only",
    r"full E2E green",
    r"works out of the box",
    r"just clone and run",
)
_QUICKSTART_CLAIM: Final = (
    r"(?=.{0,200}\bquickstart\b)"
    r"(?=.{0,200}\b(?:real|live|production)\b)"
    r"(?=.{0,200}\b(?:Discord|mail|calendar|deploy)\b).{1,200}"
)


def rules() -> tuple[Rule, ...]:
    return (Rule("DOCS-FORBIDDEN-CLAIM", rf"(?:{'|'.join(_DIRECT_CLAIMS)}|{_QUICKSTART_CLAIM})"),)
