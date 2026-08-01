"""Regression: the batch digest must stay an approval-decision surface, not a file dump (E11).

The first full sync rendered 361 file paths as an 1859-char / 32-line wall, so the
#approvals message stopped being usable as an approval-decision surface — the owner
could not see what was being approved without scrolling past the paths (owner feedback
2026-07-25). Above the list limit the digest now aggregates by archive class; at or
below it the paths are still listed, because for a small delta the paths ARE the
information.

Invariants these tests protect: the literal action_hash stays in the text (the watcher
binds the owner's ✅ via ``pending.action_hash in message_content``, fail closed
otherwise), the message stays within Discord's 2000-char limit, and the true total is
always reported — every in-scope file uploads regardless of what the body displays.
"""

from __future__ import annotations

from automation.drive_archive import digest
from automation.drive_archive.manifest import BatchManifest, FileEntry
from automation.interop.approval_surface import (
    ApprovalKind,
    ApprovalSurface,
    reaction_instruction,
)

_HASH = "sha256:" + "d" * 64
_ROOT = "Autophagy 문서아카이브"


def _request(
    files: tuple[FileEntry, ...], tracked: frozenset[str] = frozenset()
) -> digest.DigestRequest:
    return digest.DigestRequest(
        BatchManifest(project="autophagy-agents", files=files), _HASH, _ROOT, tracked
    )


def test_large_batch_aggregates_by_class_instead_of_listing_paths() -> None:
    # Given: the real first-full-sync distribution (361 files), synthetic and stable
    paths = [
        *(f"docs/qa/E11-{i % 9}/{i:03d}-evidence.md" for i in range(329)),
        *(f"docs/patch/2026-07-{i:02d}-x.md" for i in range(21)),
        *(f".omo/plans/p{i}.md" for i in range(6)),
        *(f".omo/notepads/s{i}/n.md" for i in range(4)),
        "docs/features.md",
    ]
    files = tuple(FileEntry(path, f"{i:064x}") for i, path in enumerate(paths))
    assert len(files) == 361  # fixture guard: a fixture bug must never look like a renderer bug

    # When
    text = digest.render(_request(files))

    # Then: the true total and the new/changed split survive
    assert "대상 파일 361건" in text
    assert "신규 361 · 변경 0" in text

    # Then: the class table is an exact consecutive block (locks counts, order, tie-break)
    lines = text.splitlines()
    start = lines.index("분류별 집계")
    assert lines[start : start + 6] == [
        "분류별 집계",
        "- `qa/` 329건",
        "- `patch/` 21건",
        "- `plans/` 6건",
        "- `notepads/` 4건",
        "- `features/` 1건",
    ]

    # Then: individual paths are gone, replaced by a pointer to the full listing
    assert "docs/qa/E11-0/000-evidence.md" not in text
    assert "전체 목록: `python3 -m automation.drive_archive.sync_cli plan`" in text

    # Then: the binding + destination survive, within the Discord budget
    assert _HASH in text
    assert _ROOT in text
    assert len(text) <= 2000
    assert len(text.splitlines()) <= 16


def test_added_and_updated_split_comes_from_the_cursor() -> None:
    # Given: three files, one of which the cursor already tracks
    files = (
        FileEntry("docs/qa/E11/a.md", "a" * 64),
        FileEntry("docs/qa/E11/b.md", "b" * 64),
        FileEntry("docs/qa/E11/c.md", "c" * 64),
    )

    # When
    text = digest.render(_request(files, frozenset({"docs/qa/E11/b.md"})))

    # Then
    assert "대상 파일 3건 · 신규 2 · 변경 1" in text


def test_batch_at_list_limit_lists_every_path() -> None:
    # Given: exactly the list limit
    files = tuple(FileEntry(f"docs/qa/E11/{i:02d}.md", f"{i:064x}") for i in range(12))

    # When
    text = digest.render(_request(files))

    # Then: for a small delta the paths ARE the information
    for entry in files:
        assert entry.path in text
    assert "분류별 집계" not in text
    assert "…외" not in text


def test_batch_above_list_limit_switches_to_aggregate() -> None:
    # Given: one file past the list limit
    files = (
        *(FileEntry(f"docs/qa/E11/{i:02d}.md", f"{i:064x}") for i in range(12)),
        FileEntry("docs/qa/E11/12.md", f"{12:064x}"),
    )

    # When
    text = digest.render(_request(files))

    # Then
    assert "분류별 집계" in text
    assert "docs/qa/E11/00.md" not in text


def test_pathological_batch_stays_within_discord_limit() -> None:
    # Given: 5000 ~300-char paths under 500-char project and root labels
    files = tuple(
        FileEntry(f"docs/qa/E11-{i:04d}/{'p' * 280}.md", f"{i:064x}") for i in range(5000)
    )
    request = digest.DigestRequest(
        BatchManifest(project="P" * 500, files=files), _HASH, "R" * 500, frozenset()
    )

    # When
    text = digest.render(request)

    # Then
    assert len(text) <= 2000
    assert _HASH in text
    assert "대상 파일 5000건" in text
    assert "전체 목록" in text


def test_single_long_path_batch_lists_it_in_full() -> None:
    # Given: one file whose path alone is 300+ chars
    path = "docs/qa/E11/" + "l" * 300 + ".md"
    files = (FileEntry(path, "e" * 64),)

    # When
    text = digest.render(_request(files))

    # Then: a single path is never worth truncating
    assert path in text
    assert len(text) <= 2000
    assert "…외" not in text


def test_the_digest_asks_for_a_decision_in_the_policy_wording() -> None:
    # Given: the one formatter allowed to phrase an owner reaction instruction.
    expected = reaction_instruction(ApprovalKind.DRIVE_ARCHIVE, ApprovalSurface.OWNER_DM)

    # When: a digest is rendered for a batch the owner must decide on.
    files = (FileEntry("docs/features.md", "a" * 64), FileEntry(".omo/plans/a.md", "b" * 64))
    text = digest.render(_request(files))

    # Then: it carries that exact line, still states what ✅ commits the owner to,
    # and names no surface — the approval message says how to answer, not where it
    # lives — while the action_hash the watcher content-binds on is untouched.
    assert expected in text
    assert "✅ = 2건 전체 업로드" in text
    assert "#approvals" not in text
    assert "DM" not in text
    assert _HASH in text
