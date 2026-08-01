from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import override

from repo_scan_engine import scan
from repo_scan_models import Check, Finding, Profile, ScanConfig


_USAGE = (
    "usage: repo_scan.py --profile {public-generic,docs-claims} --root DIR "
    "[--checks paths,symlinks,binaries,excluded-dirs] [--json]"
)


@dataclass(frozen=True, slots=True)
class CliError(Exception):
    message: str

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class CliOptions:
    config: ScanConfig
    json_output: bool


def main(arguments: Sequence[str] | None = None) -> int:
    actual = sys.argv[1:] if arguments is None else arguments
    try:
        return run(parse_options(actual))
    except CliError as error:
        print(error, file=sys.stderr)
        return 2


def parse_options(arguments: Sequence[str]) -> CliOptions:
    values, flags = _option_values(arguments)
    profile = _profile(values.get("--profile"))
    root = _root(values.get("--root"))
    return CliOptions(ScanConfig(profile, root, _checks(values.get("--checks"))), "--json" in flags)


def run(options: CliOptions) -> int:
    findings = scan(options.config)
    for finding in findings:
        print(_line(finding, options.json_output))
    state = "CLEAN" if not findings else "DIRTY"
    print(f"SCAN-{state} profile={options.config.profile} findings={len(findings)}")
    if any(finding.rule_id == "IO-ERROR" for finding in findings):
        return 2
    return 0 if not findings else 1


def _option_values(arguments: Sequence[str]) -> tuple[dict[str, str], frozenset[str]]:
    values: dict[str, str] = {}
    flags: set[str] = set()
    value_options = frozenset({"--profile", "--root", "--checks"})
    flag_options = frozenset({"--json"})
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in flag_options:
            flags.add(argument)
            index += 1
            continue
        if argument not in value_options or index + 1 >= len(arguments):
            raise CliError(_USAGE)
        values[argument] = arguments[index + 1]
        index += 2
    return values, frozenset(flags)


def _profile(raw: str | None) -> Profile:
    if raw is None:
        raise CliError(_USAGE)
    try:
        return Profile(raw)
    except ValueError as error:
        raise CliError(_USAGE) from error


def _root(raw: str | None) -> Path:
    if raw is None:
        raise CliError(_USAGE)
    root = Path(raw).resolve()
    if not root.is_dir():
        raise CliError(f"scan root is not a readable directory: {raw}")
    return root


def _checks(raw: str | None) -> frozenset[Check]:
    if raw is None or not raw.strip():
        return frozenset()
    checks: set[Check] = set()
    for value in raw.split(","):
        try:
            checks.add(Check(value.strip()))
        except ValueError as error:
            raise CliError(f"unknown structural check: {value}") from error
    return frozenset(checks)


def _line(finding: Finding, json_output: bool) -> str:
    if json_output:
        return json.dumps(
            {
                "line": finding.line,
                "match": finding.match,
                "path": finding.path,
                "rule_id": finding.rule_id,
                "severity": finding.severity,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    suffix = "" if finding.match is None else f" match={json.dumps(finding.match, ensure_ascii=False)}"
    return f"{finding.severity} {finding.rule_id} {finding.path}:{finding.line}{suffix}"
