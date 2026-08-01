from __future__ import annotations

import ast
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


def _workflow_files() -> list[Path]:
    workflows = REPO_ROOT / ".github" / "workflows"
    return sorted(p for p in workflows.glob("*.y*ml") if p.is_file())


def _unterminated_quoted_scalars(text: str) -> list[str]:
    """Lines whose value opens with a quote but carries unquoted trailing content.

    YAML reads ``run: "$X/bin" --flag`` as the scalar ``$X/bin`` followed by
    garbage and refuses the document. GitHub then reports only "a workflow file
    issue" and runs nothing — so a broken gate looks identical to an absent one.
    """
    offenders: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") or ":" not in stripped:
            continue
        value = stripped.split(":", 1)[1].strip()
        if not value or value[0] not in "\"'":
            continue
        quote = value[0]
        closing = value.find(quote, 1)
        if closing == -1:
            offenders.append(f"{number}: {stripped}")
            continue
        remainder = value[closing + 1 :].strip()
        if remainder and not remainder.startswith("#"):
            offenders.append(f"{number}: {stripped}")
    return offenders


def test_every_workflow_file_is_parseable_yaml() -> None:
    """A CI definition that cannot parse is a gate that silently never runs.

    This repository gates its own contents, but nothing gated the gate: the
    workflow shipped with a scalar YAML could not read, so the first push
    reported a failure without executing a single check. The lint is
    dependency-free on purpose — it has to hold in a checkout that has installed
    nothing.
    """
    # Given: the workflow definitions that CI will load.
    workflows = _workflow_files()

    # When: each is inspected for the malformed-scalar shape.
    assert workflows, "no workflow files found"
    offenders = {
        workflow.name: _unterminated_quoted_scalars(workflow.read_text(encoding="utf-8"))
        for workflow in workflows
    }

    # Then: none carries a value YAML would refuse.
    broken = {name: lines for name, lines in offenders.items() if lines}
    assert not broken, f"unparseable YAML scalars: {broken}"


def test_workflow_lint_detects_the_shape_that_shipped_broken() -> None:
    """The lint must fail on the exact line that broke CI, or it proves nothing."""
    # Given: the malformed step as it was published, and its corrected form.
    broken = '        run: "${RUNNER_TEMP}/gitleaks-bin" dir --no-banner --redact .\n'
    fixed = '        run: \'"${RUNNER_TEMP}/gitleaks-bin" dir --no-banner --redact .\'\n'

    # When: both are linted.
    broken_offenders = _unterminated_quoted_scalars(broken)
    fixed_offenders = _unterminated_quoted_scalars(fixed)

    # Then: only the published form is rejected.
    assert broken_offenders, "lint missed the shape that actually broke CI"
    assert not fixed_offenders, fixed_offenders


_ISOLATED_SUBSERVICES = ("configs/rag/", "configs/litellm-staging/")
_TEST_ONLY_DEPENDENCIES = frozenset({"pytest"})


def _module_level_imports(tree: "ast.Module") -> set[str]:
    """Top-level import roots only — imports inside a function are lazy by design."""
    roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_main_tree_imports_only_the_standard_library_at_module_level() -> None:
    """A third-party import at module scope breaks every checkout that lacks it.

    The main tree is standard-library first: optional dependencies are imported
    inside the function that needs them, behind a ``ModuleNotFoundError`` fallback.
    One module imported PyYAML at the top instead, which passed on a machine that
    happened to have it installed and failed the moment CI ran on a clean one —
    collection aborted before a single test executed. Nothing checked this, so
    "standard library first" was a claim rather than a property.

    Isolated subservices under ``configs/`` declare their own dependencies and
    lockfiles, and the test suite may use its runner; everything else must import
    only stdlib or repository-local modules at module scope.
    """
    # Given: every Python module outside the declared-dependency subtrees.
    local_roots = {
        entry.name for entry in REPO_ROOT.iterdir() if entry.is_dir() and not entry.name.startswith(".")
    }
    local_modules = set()
    for path in REPO_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        local_modules.add(path.stem)
        local_modules.add(path.parent.name)
    known = set(sys.stdlib_module_names) | local_roots | local_modules | _TEST_ONLY_DEPENDENCIES

    # When: their module-level import roots are collected.
    offenders: dict[str, set[str]] = {}
    for path in sorted(REPO_ROOT.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if "__pycache__" in path.parts or relative.startswith(_ISOLATED_SUBSERVICES):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):  # pragma: no cover - surfaced by other gates
            continue
        external = _module_level_imports(tree) - known
        if external:
            offenders[relative] = external

    # Then: none of them reaches outside the standard library.
    assert not offenders, f"module-level third-party imports: {offenders}"
