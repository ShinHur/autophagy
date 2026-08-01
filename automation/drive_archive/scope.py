"""Pure enumeration of the in-scope tracked deliverables to mirror to Drive.

Scope (owner decision 2, tracked documentation only): plans, notepads, the
features summary, per-wave QA evidence, and patch notes. Source code and
runtime paths (~/.hermes, /srv/*) are outside these globs by construction.
"""

from __future__ import annotations

from pathlib import Path

SCOPE_GLOBS: tuple[str, ...] = (
    ".omo/plans/*.md",
    ".omo/plans/archive/*.md",
    ".omo/notepads/**/*.md",
    "docs/features.md",
    "docs/qa/**/*",
    "docs/patch/*.md",
)


def enumerate_scope(root: Path) -> tuple[str, ...]:
    """Return in-scope files as sorted, deduplicated repo-relative POSIX paths."""
    seen: set[str] = set()
    for pattern in SCOPE_GLOBS:
        for match in root.glob(pattern):
            if match.is_file():
                seen.add(match.relative_to(root).as_posix())
    return tuple(sorted(seen))
