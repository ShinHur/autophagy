"""Regression: the batch digest must fit Discord's 2000-char message limit (E11).

The first full sync lists ~360 deliverables; above the list limit the digest
aggregates the batch by archive class (instead of listing paths) while keeping
the action_hash for reaction binding, so the #approvals POST never fails with
HTTP 400 on length.
"""

from __future__ import annotations

from automation.drive_archive import digest
from automation.drive_archive.manifest import BatchManifest, FileEntry


def test_digest_fits_discord_2000_char_limit() -> None:
    files = tuple(
        FileEntry(f"docs/qa/W{i % 7}-{i}/{i:03d}-long-evidence-file-name.md", f"{i:064x}")
        for i in range(400)
    )
    action_hash = "sha256:" + "d" * 64
    text = digest.render(
        digest.DigestRequest(
            BatchManifest(project="autophagy-agents", files=files),
            action_hash,
            "Autophagy 문서아카이브",
            frozenset(),
        )
    )

    assert len(text) <= 2000  # Discord message limit
    assert action_hash in text  # reaction binding preserved
    assert "대상 파일 400건" in text  # true total still reported (not the truncated count)
    assert "- `qa/` 400건" in text  # intent transfer: the full scope is disclosed as a class aggregate,
    assert "docs/qa/W0-0/000-long-evidence-file-name.md" not in text  # not as a truncated path list,
    assert "전체 목록" in text  # and the complete list stays reachable


def test_digest_small_batch_lists_all_without_overflow() -> None:
    files = (FileEntry("docs/features.md", "a" * 64), FileEntry(".omo/plans/a.md", "b" * 64))
    text = digest.render(
        digest.DigestRequest(
            BatchManifest(project="p", files=files), "sha256:" + "c" * 64, "루트", frozenset()
        )
    )

    assert "docs/features.md" in text
    assert ".omo/plans/a.md" in text
    assert "…외" not in text  # small batch: full list, no truncation
