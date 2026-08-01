from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum, unique
from pathlib import Path
from typing import Protocol


@unique
class Profile(StrEnum):
    PUBLIC_GENERIC = "public-generic"
    DOCS_CLAIMS = "docs-claims"


@unique
class Severity(StrEnum):
    ERROR = "ERROR"
    WARN = "WARN"


@unique
class Check(StrEnum):
    PATHS = "paths"
    SYMLINKS = "symlinks"
    BINARIES = "binaries"
    EXCLUDED_DIRS = "excluded-dirs"


class MatchPredicate(Protocol):
    def __call__(self, candidate: re.Match[str]) -> bool: ...


@dataclass(frozen=True, slots=True)
class Rule:
    rule_id: str
    pattern: str
    severity: Severity = Severity.ERROR
    flags: int = re.IGNORECASE
    accept: MatchPredicate | None = None


@dataclass(frozen=True, slots=True)
class TextView:
    text: str
    source_line: int | None = None


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    path: str
    line: int
    severity: Severity
    match: str | None = None


@dataclass(frozen=True, slots=True)
class ScanConfig:
    profile: Profile
    root: Path
    checks: frozenset[Check]
