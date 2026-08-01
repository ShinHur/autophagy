"""Routing is ONE table: the digest's class and the uploader's folder path agree (E11)."""

from __future__ import annotations

from automation.drive_archive import routing, uploader


def test_classify_agrees_with_route_parts_for_every_class() -> None:
    cases = (
        (".omo/plans/x.md", "plans"),
        (".omo/plans/archive/x.md", "plans"),
        (".omo/notepads/slug/decisions.md", "notepads"),
        ("docs/features.md", "features"),
        ("docs/qa/E11/00-note.txt", "qa"),
        ("docs/patch/2026-07-24-x.md", "patch"),
        ("README.md", "misc"),
    )
    for rel, expected in cases:
        assert routing.classify(rel) == expected, rel
        assert uploader.route_parts("A", rel)[1] == expected, rel  # one table, two views
