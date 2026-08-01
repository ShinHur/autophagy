from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import assert_never, override

from repo_scan_filesystem import selected_paths
from repo_scan_models import Check, Finding, MatchPredicate, Profile, Rule, ScanConfig, Severity, TextView
from repo_scan_normalizers import generic_views
from repo_scan_structural import binary_kind, excluded_directory, generic_forbidden_filename, symlink_resolves_outside


@dataclass(frozen=True, slots=True)
class RuleSetError(Exception):
    rule_id: str

    @override
    def __str__(self) -> str:
        return f"malformed rule: {self.rule_id}"


@dataclass(frozen=True, slots=True)
class CompiledRule:
    rule_id: str
    pattern: re.Pattern[str]
    severity: Severity
    accept: MatchPredicate | None


def scan(config: ScanConfig) -> tuple[Finding, ...]:
    try:
        rules = _compile_rules(config.profile)
    except (RuleSetError, re.error):
        return (Finding("RULESET-ERROR", ".", 1, Severity.ERROR),)
    return Scanner(config, rules).run()


def _compile_rules(profile: Profile) -> tuple[CompiledRule, ...]:
    compiled: list[CompiledRule] = []
    for rule in _profile_rules(profile):
        if not rule.rule_id or not rule.pattern:
            raise RuleSetError(rule_id=rule.rule_id or "<empty>")
        try:
            pattern = re.compile(rule.pattern, rule.flags)
        except re.error as error:
            raise RuleSetError(rule_id=rule.rule_id) from error
        compiled.append(CompiledRule(rule.rule_id, pattern, rule.severity, rule.accept))
    return tuple(compiled)


def _profile_rules(profile: Profile) -> tuple[Rule, ...]:
    match profile:
        case Profile.PUBLIC_GENERIC:
            from rules.public_generic import rules

            return rules()
        case Profile.DOCS_CLAIMS:
            from rules.docs_claims import rules

            return rules()
        case unreachable:
            assert_never(unreachable)


@dataclass(frozen=True, slots=True)
class Scanner:
    config: ScanConfig
    rules: tuple[CompiledRule, ...]

    def run(self) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        walked = selected_paths(self.config.root)
        for error_path in walked.errors:
            findings.append(Finding("IO-ERROR", self._relative(error_path), 1, Severity.ERROR))
        for path in walked.paths:
            findings.extend(self._scan_path(path))
        unique = {
            (finding.rule_id, finding.path, finding.line, finding.severity, finding.match): finding
            for finding in findings
        }
        return tuple(sorted(unique.values(), key=lambda item: (item.path, item.line, item.rule_id)))

    def _scan_path(self, path: Path) -> tuple[Finding, ...]:
        relative = self._relative(path)
        findings = list(self._path_findings(path, relative))
        if path.is_symlink():
            findings.extend(self._symlink_findings(path, relative))
            return tuple(findings)
        if not path.is_file():
            return tuple(findings)
        if self.config.checks and Check.BINARIES not in self.config.checks:
            return tuple(findings)
        if not self.config.checks and not self._content_in_scope(path):
            return tuple(findings)
        try:
            data = path.read_bytes()
        except OSError:
            findings.append(Finding("IO-ERROR", relative, 1, Severity.ERROR))
            return tuple(findings)
        findings.extend(self._scan_bytes(data, relative))
        return tuple(findings)

    def _path_findings(self, path: Path, relative: str) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        if Check.PATHS in self.config.checks:
            generic_match = generic_forbidden_filename(path.name)
            if generic_match is not None:
                findings.append(Finding("FORBIDDEN-FILENAME", relative, 1, Severity.ERROR, generic_match))
            if path.name == ".gitmodules":
                findings.append(Finding("GITMODULES", relative, 1, Severity.ERROR, ".gitmodules"))
        if Check.EXCLUDED_DIRS in self.config.checks and excluded_directory(PurePosixPath(relative)):
            findings.append(Finding("EXCLUDED-DIR", relative, 1, Severity.ERROR, relative))
        return tuple(findings)


    def _symlink_findings(self, path: Path, relative: str) -> tuple[Finding, ...]:
        if Check.SYMLINKS not in self.config.checks:
            return ()
        try:
            outside = symlink_resolves_outside(self.config.root, path)
            target = os.readlink(path)
        except OSError:
            return (Finding("IO-ERROR", relative, 1, Severity.ERROR),)
        if outside:
            return (Finding("SYMLINK-OUTSIDE", relative, 1, Severity.ERROR, target),)
        return ()

    def _scan_bytes(self, data: bytes, relative: str) -> tuple[Finding, ...]:
        if self.config.checks:
            kind = binary_kind(data)
            if kind is None:
                return ()
            return (Finding("BINARY-CONTAINER", relative, 1, Severity.ERROR, kind),)
        kind = binary_kind(data)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return (Finding("UNDECODABLE", relative, 1, Severity.ERROR),)
        return self._match_views(generic_views(text), relative)

    def _match_views(self, views: tuple[TextView, ...], relative: str) -> tuple[Finding, ...]:
        findings: list[Finding] = []
        for view in views:
            for rule in self.rules:
                for candidate in rule.pattern.finditer(view.text):
                    if rule.accept is not None and not rule.accept(candidate):
                        continue
                    line = view.source_line or view.text.count("\n", 0, candidate.start()) + 1
                    findings.append(Finding(rule.rule_id, relative, line, rule.severity, candidate.group(0)))
        return tuple(findings)

    def _content_in_scope(self, path: Path) -> bool:
        return self.config.profile is not Profile.DOCS_CLAIMS or path.suffix.lower() == ".md"

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.config.root).as_posix()
        except ValueError:
            return path.name
