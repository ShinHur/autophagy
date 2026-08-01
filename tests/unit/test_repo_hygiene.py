from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNER = REPO_ROOT / "tools" / "repo_scan.py"


def _run_scanner(
    root: Path,
    profile: str,
    checks: str | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCANNER), "--profile", profile, "--root", str(root)]
    if checks is not None:
        command.extend(("--checks", checks))
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        cwd=REPO_ROOT,
        env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]},
        text=True,
    )


def test_public_generic_profile_rejects_sensitive_fixture_and_accepts_placeholder(tmp_path: Path) -> None:
    # Given: separate sensitive and placeholder-only fixture trees.
    sensitive = tmp_path / "sensitive"
    clean = tmp_path / "clean"
    sensitive.mkdir()
    clean.mkdir()
    (sensitive / "input.txt").write_text("contact=operator" + "@" + "organization.test", encoding="utf-8")
    (clean / "input.txt").write_text("contact=help" + "@" + "example.org", encoding="utf-8")

    # When: the public generic profile scans each tree without a private rule module.
    assert not (REPO_ROOT / "tools" / "rules" / "private_literals.py").exists()
    sensitive_result = _run_scanner(sensitive, "public-generic")
    clean_result = _run_scanner(clean, "public-generic")

    # Then: it rejects the sensitive class and accepts the documented placeholder.
    assert sensitive_result.returncode == 1
    assert "GENERIC-EMAIL" in sensitive_result.stdout
    assert clean_result.returncode == 0
    assert clean_result.stdout.splitlines()[-1] == "SCAN-CLEAN profile=public-generic findings=0"


def test_docs_claims_profile_rejects_marketing_claim_and_ignores_non_markdown(tmp_path: Path) -> None:
    # Given: a Markdown marketing claim and the same text in a non-Markdown file.
    markdown = tmp_path / "markdown"
    non_markdown = tmp_path / "non-markdown"
    markdown.mkdir()
    non_markdown.mkdir()
    claim = "This project is production" + "-ready."
    (markdown / "README.md").write_text(claim, encoding="utf-8")
    (non_markdown / "claim.txt").write_text(claim, encoding="utf-8")

    # When: the claims profile scans both fixture trees.
    markdown_result = _run_scanner(markdown, "docs-claims")
    non_markdown_result = _run_scanner(non_markdown, "docs-claims")

    # Then: it rejects the public claim only in Markdown scope.
    assert markdown_result.returncode == 1
    assert "DOCS-FORBIDDEN-CLAIM" in markdown_result.stdout
    assert non_markdown_result.returncode == 0
    assert non_markdown_result.stdout.splitlines()[-1] == "SCAN-CLEAN profile=docs-claims findings=0"


def test_cli_returns_one_when_public_generic_fixture_is_dirty(tmp_path: Path) -> None:
    # Given: a fixture with a scanner-detectable non-synthetic snowflake.
    fixture = tmp_path / "dirty"
    fixture.mkdir()
    marker = "".join(chr(code) for code in (50, 56, 48, 54, 56, 48, 53, 55, 56, 51, 49, 52, 48, 49, 48, 54, 50, 53))
    (fixture / "input.txt").write_text(f"owner id {marker}\n", encoding="utf-8")

    # When: the public profile scans the dirty fixture.
    result = _run_scanner(fixture, "public-generic")

    # Then: a dirty scan is a blocking failure.
    assert result.returncode == 1


def test_cli_returns_zero_when_public_generic_fixture_is_clean(tmp_path: Path) -> None:
    # Given: a fixture without any public-generic finding.
    fixture = tmp_path / "clean"
    fixture.mkdir()
    (fixture / "input.txt").write_text("hello world\n", encoding="utf-8")

    # When: the public profile scans the clean fixture.
    result = _run_scanner(fixture, "public-generic")

    # Then: a clean scan succeeds.
    assert result.returncode == 0


def test_cli_returns_two_when_tree_cannot_be_read(tmp_path: Path) -> None:
    # Given: a scan tree containing an unreadable directory.
    root = tmp_path / "root"
    unreadable = root / "unreadable"
    unreadable.mkdir(parents=True)
    (unreadable / "input.txt").write_text("hello world\n", encoding="utf-8")

    # When: the public profile encounters the filesystem error.
    unreadable.chmod(0)
    try:
        result = _run_scanner(root, "public-generic")
    finally:
        unreadable.chmod(0o700)

    # Then: an I/O error uses the operational-error status.
    assert result.returncode == 2
    assert "IO-ERROR" in result.stdout


def test_public_generic_accepts_documented_fixture_classes(tmp_path: Path) -> None:
    # Given: reserved fixtures plus a numeric run inside a hexadecimal digest.
    fixture = tmp_path / "fixture-classes"
    fixture.mkdir()
    token_prefix = "sk" + "-"
    lines = (
        token_prefix + "repair-fixture-token",
        token_prefix + "secretvalue",
        token_prefix + "live-secret-value-12345",
        "-----BEGIN " + "PRIVATE KEY-----",
        "person" + "@example.test",
        "snap" + "@test.local",
        "git" + "@github.com",
        "git" + "@git.example.invalid",
        "agent" + "@corp.example.org",
        "person" + "@inst.example",
        "/home/" + "ops",
        "/home/" + "agent",
        "박사" + "님",
        "이름 충돌은",
        "sha256:" + "a" + "123456789" + "012345678" + "b",
        "version = \"" + "10.4" + ".0.35\"",
    )
    (fixture / "input.txt").write_text("\n".join(lines), encoding="utf-8")

    # When: the public profile scans the documented fixture classes.
    result = _run_scanner(fixture, "public-generic")

    # Then: narrow fixture exceptions do not suppress unrelated dirty data.
    assert result.returncode == 0


def test_public_generic_rejects_pem_key_material_after_fixture_header(tmp_path: Path) -> None:
    # Given: a private-key header followed by encoded key material.
    fixture = tmp_path / "pem-material"
    fixture.mkdir()
    content = "-----BEGIN " + "PRIVATE KEY-----\n" + "A" * 16
    (fixture / "input.txt").write_text(content, encoding="utf-8")

    # When: the public profile scans the complete key-like value.
    result = _run_scanner(fixture, "public-generic")

    # Then: header-only fixtures do not suppress key material.
    assert result.returncode == 1
    assert "GENERIC-TOKEN" in result.stdout


def test_structural_checks_exclude_content_rules_and_report_requested_checks(tmp_path: Path) -> None:
    # Given: a tree with every structural violation and a content-only marker.
    root = tmp_path / "root"
    root.mkdir()
    marker = "".join(chr(code) for code in (50, 56, 48, 54, 56, 48, 53, 55, 56, 51, 49, 52, 48, 49, 48, 54, 50, 53))
    (root / "content.txt").write_text(f"owner id {marker}\n", encoding="utf-8")
    forbidden_filename = "".join(chr(code) for code in (111, 114, 105)) + "zzzz"
    (root / forbidden_filename).write_text("safe text\n", encoding="utf-8")
    (root / "binary.bin").write_bytes(b"\x89PNG\r\n\x1a\n")
    excluded = root / "docs" / "qa"
    excluded.mkdir(parents=True)
    (excluded / "trace.txt").write_text("safe text\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("safe text\n", encoding="utf-8")
    (root / "outside-link").symlink_to(outside)

    # When: all structural checks are selected.
    result = _run_scanner(root, "public-generic", "paths,symlinks,binaries,excluded-dirs")

    # Then: structural findings are reported without re-running content rules.
    assert result.returncode == 1
    assert "FORBIDDEN-FILENAME" in result.stdout
    assert "SYMLINK-OUTSIDE" in result.stdout
    assert "BINARY-CONTAINER" in result.stdout
    assert "EXCLUDED-DIR" in result.stdout
    assert "GENERIC-SNOWFLAKE" not in result.stdout


def test_derived_artifacts_are_skipped_while_source_is_still_scanned(tmp_path: Path) -> None:
    """A build artifact must not fail the gate, but source next to it still must.

    ``__pycache__`` and ``*.pyc`` are regenerated by every test run and are ignored
    by version control, so they can never reach a published tree. Scanning them made
    the gate fail immediately after ``pytest`` — the exact workflow CONTRIBUTING.md
    prescribes — which trains contributors to ignore it. Skipping them must not blunt
    the gate: an identical leak in real source has to keep failing.
    """
    # Given: the same sensitive marker in a derived artifact and in tracked source.
    root = tmp_path / "root"
    (root / "__pycache__").mkdir(parents=True)
    (root / "src").mkdir()
    marker = "".join(
        chr(code)
        for code in (50, 56, 48, 54, 56, 48, 53, 55, 56, 51, 49, 52, 48, 49, 48, 54, 50, 53)
    )
    (root / "__pycache__" / "derived.txt").write_text(f"owner id {marker}\n", encoding="utf-8")
    (root / "cached.pyc").write_bytes(b"\x00\x01derived bytecode")

    # When: the tree holds only derived artifacts carrying the marker.
    clean = _run_scanner(root, "public-generic")

    # Then: the gate passes, because none of it can ever be published.
    assert clean.returncode == 0, clean.stdout

    # When: the identical marker also appears in real source.
    (root / "src" / "leak.py").write_text(f"owner_id = '{marker}'\n", encoding="utf-8")
    dirty = _run_scanner(root, "public-generic")

    # Then: the gate still fails, and names only the source file.
    assert dirty.returncode == 1, dirty.stdout
    assert "src/leak.py" in dirty.stdout
    assert "__pycache__" not in dirty.stdout
    assert "cached.pyc" not in dirty.stdout
