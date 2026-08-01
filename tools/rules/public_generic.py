from __future__ import annotations

import re
from typing import Final

from repo_scan_models import Rule, Severity


_SYNTHETIC_ID: Final = re.compile(r"1000000000000000\d\d\Z")
# Generic service accounts identify roles rather than people.
_ALLOWED_HOME_NAMES: Final = frozenset({"agent", "ops", "user", "youruser", "$USER"})
# Reserved/example domains cannot route test mail to a real recipient.
_ALLOWED_EMAIL_DOMAINS: Final = frozenset(
    {"example.invalid", "example.com", "example.org", "example.test", "localhost", "test.local"}
)
_ALLOWED_EMAIL_SUFFIXES: Final = (
    ".example",
    ".example.com",
    ".example.invalid",
    ".example.org",
    ".example.test",
)
# Generic Git SSH principals name repository endpoints, not mailboxes.
_GENERIC_GIT_SSH_PRINCIPAL: Final = re.compile(r"git@(?:github|gitlab|bitbucket)\.(?:com|org|net)\Z")
# Redaction fixtures use semantic placeholder components instead of credentials.
# The PEM banner is assembled from parts so this ruleset never itself contains a
# credential-shaped literal — a detector that trips other secret scanners blocks
# releases for a string that is a pattern, not a secret.
_PEM_BEGIN: Final = "-" * 5 + "BEGIN PRIVATE KEY" + "-" * 5
_FIXTURE_TOKEN: Final = re.compile(
    r"(?:sk-(?:[a-z]+-)*(?:(?:fixture-)?token|secret-?value)(?:-\d+)?|"
    + re.escape(_PEM_BEGIN)
    + r")\Z"
)
_PEM_KEY_MATERIAL: Final = re.compile(r"\s*\n[A-Za-z0-9+/=]{16,}")
# Academic titles are honorifics rather than person names.
_HANGUL_TITLE_HONORIFIC: Final = re.compile(r"(?:[가-힣]+\s*[:=]?\s*)?(?:박사|교수|선생)님\Z")
# Package version syntax is not a network address.
_PACKAGE_VERSION: Final = re.compile(r"(?:^\s*version\s*=\s*\"\d+(?:\.\d+){2,}\"\s*$|[-_]\d+(?:\.\d+){2,}(?:[-_]|\.whl))")


def rules() -> tuple[Rule, ...]:
    return (
        Rule("GENERIC-SNOWFLAKE", r"(?<![0-9A-Fa-f])\d{17,20}(?![0-9A-Fa-f])", accept=_real_snowflake),
        Rule("GENERIC-IP", r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)", accept=_sensitive_ipv4),
        Rule("GENERIC-HOME-PATH", r"/home/(?P<name>[A-Za-z0-9_$.-]+)", accept=_private_home),
        Rule("GENERIC-SRV-LITERAL", r"(?P<q>['\"])/srv/(?P=q)"),
        Rule(
            "GENERIC-EMAIL",
            r"\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@(?P<domain>[A-Z0-9.-]+\.[A-Z]{2,}|localhost)\b",
            accept=_sensitive_email,
        ),
        Rule(
            "GENERIC-GOOGLE-ID",
            r"(?:docs\.google\.com/(?:spreadsheets|drive)/[^\s'\"]{0,80}|(?:sheet|drive)(?:_id)?\s*[:=]\s*['\"]?)[A-Za-z0-9_-]{40,50}\b",
        ),
        Rule(
            "GENERIC-GCP-PROJECT",
            r"(?:gcp[_-]?project|project[_-]?id)\s*[:=]\s*['\"]?[a-z][a-z0-9-]{4,28}[a-z0-9]",
        ),
        Rule("GENERIC-GOOGLE-OAUTH", r"\b[a-z0-9.-]+\.apps\.googleusercontent\.com\b"),
        Rule(
            "GENERIC-TOKEN",
            r"(?:\bsk-[A-Za-z0-9_-]{8,}|\bgh[po]_[A-Za-z0-9]{8,}|\bgithub_pat_[A-Za-z0-9_]{8,}|\bxoxb-[A-Za-z0-9-]{8,}|\bAIza[0-9A-Za-z_-]{35}\b|\bya29\.[A-Za-z0-9._-]{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
            accept=_sensitive_token,
        ),
        Rule(
            "GENERIC-HANGUL-NAME",
            r"(?:(?:이름|참석|작성자)\s*[:=]\s*[가-힣]{2,4}|[가-힣]{2,4}(?:님|씨|올림|드림))",
            severity=Severity.WARN,
            accept=_personal_hangul_reference,
        ),
    )


def _real_snowflake(candidate: re.Match[str]) -> bool:
    return _SYNTHETIC_ID.fullmatch(candidate.group(0)) is None


def _sensitive_ipv4(candidate: re.Match[str]) -> bool:
    first, second, third, fourth = (int(part) for part in candidate.group(0).split("."))
    if max(first, second, third, fourth) > 255:
        return False
    line_start = candidate.string.rfind("\n", 0, candidate.start()) + 1
    line_end = candidate.string.find("\n", candidate.end())
    line = candidate.string[line_start : None if line_end == -1 else line_end]
    if _PACKAGE_VERSION.search(line) is not None:
        return False
    return first == 10 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168) or (first == 100 and 64 <= second <= 127)


def _private_home(candidate: re.Match[str]) -> bool:
    return candidate.group("name") not in _ALLOWED_HOME_NAMES


def _sensitive_email(candidate: re.Match[str]) -> bool:
    domain = candidate.group("domain").lower()
    return (
        domain not in _ALLOWED_EMAIL_DOMAINS
        and not domain.endswith(_ALLOWED_EMAIL_SUFFIXES)
        and _GENERIC_GIT_SSH_PRINCIPAL.fullmatch(candidate.group(0)) is None
    )


def _sensitive_token(candidate: re.Match[str]) -> bool:
    if candidate.group(0).startswith("-----BEGIN "):
        return _PEM_KEY_MATERIAL.match(candidate.string, candidate.end()) is not None
    return _FIXTURE_TOKEN.fullmatch(candidate.group(0)) is None


def _personal_hangul_reference(candidate: re.Match[str]) -> bool:
    return _HANGUL_TITLE_HONORIFIC.fullmatch(candidate.group(0)) is None
