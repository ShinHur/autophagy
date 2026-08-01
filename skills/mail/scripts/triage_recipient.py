"""Recipient-role detection: is the owner a To or only a Cc (참조) recipient?

The generic backend body may start with a YAML-ish frontmatter block carrying
``to:``/``cc:`` lines. This module compares those addresses with OWNER_EMAIL:

- ``"to"``      owner appears in To (reply expectations unchanged)
- ``"cc"``      owner appears ONLY in Cc — not a reply target (owner decision
                2026-07-19: digest/summaries must bucket these as 참조)
- ``"unknown"`` owner address unavailable or frontmatter absent/unparsable —
                callers keep today's behavior (fail-open)

"""
from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timedelta

import site_mail_backend

_ADDR = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def owner_address() -> str:
    config_env = site_mail_backend._config_env()
    try:
        return str(config_env.owner_email())
    except config_env.ConfigError:
        return ""


def parse_recipients(markdown: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(to_addresses, cc_addresses) from the leading frontmatter block only.

    Addresses are lowercased. Any shape problem yields empty tuples — the
    caller degrades to role ``unknown`` (today's behavior).
    """
    if not markdown.startswith("---"):
        return (), ()
    parts = markdown.split("---", 2)
    if len(parts) < 3:
        return (), ()
    found: dict[str, tuple[str, ...]] = {}
    for line in parts[1].splitlines():
        key = line.split(":", 1)[0].strip().lower()
        if key in ("to", "cc") and key not in found:
            value = line.split(":", 1)[1]
            found[key] = tuple(addr.lower() for addr in _ADDR.findall(value))
    return found.get("to", ()), found.get("cc", ())


def recipient_role(markdown: str, owner: str) -> str:
    """``"to"`` | ``"cc"`` | ``"unknown"`` for the owner in this mail."""
    owner_normalized = (owner or "").strip().lower()
    if not owner_normalized:
        return "unknown"
    to_addresses, cc_addresses = parse_recipients(markdown)
    if owner_normalized in to_addresses:
        return "to"
    if owner_normalized in cc_addresses:
        return "cc"
    return "unknown"


_SUBJECT_STOPWORDS = frozenset({"re", "fw", "fwd"})
_CREATED_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _subject_tokens(subject: str) -> frozenset[str]:
    tokens = re.findall(r"[0-9A-Za-z가-힣]{2,}", subject.lower())
    return frozenset(token for token in tokens if token not in _SUBJECT_STOPWORDS)


def _addresses(joined: str) -> frozenset[str]:
    return frozenset(
        part.strip().lower() for part in joined.split(",") if part.strip())


def related_recipient_gap(
    new_to: str,
    new_subject: str,
    drafts: Iterable[dict],
    *,
    now_utc: str,
    window_hours: int = 24,
) -> list[str]:
    """Recipients of recent related SENT composes missing from a new compose.

    Deterministic assist for the contextual-omission failure (2026-07-20: a
    follow-up confirmation mail silently dropped one participant). Considers
    only executed compose drafts within the window whose subject shares at
    least one meaningful token; returns the sorted missing addresses. Any
    unparsable record is skipped (warning-only surface — never blocks).
    """
    try:
        now = datetime.strptime(now_utc, _CREATED_FORMAT)
    except (TypeError, ValueError):
        return []
    window = timedelta(hours=window_hours)
    new_tokens = _subject_tokens(new_subject)
    new_addresses = _addresses(new_to)
    union: set[str] = set()
    for draft in drafts:
        if draft.get("kind") != "compose" or draft.get("status") != "executed":
            continue
        try:
            created = datetime.strptime(str(draft.get("created")), _CREATED_FORMAT)
        except (TypeError, ValueError):
            continue
        if not (timedelta(0) <= now - created <= window):
            continue
        if not (new_tokens & _subject_tokens(str(draft.get("subject") or ""))):
            continue
        union |= _addresses(str(draft.get("to") or ""))
    return sorted(union - new_addresses)
