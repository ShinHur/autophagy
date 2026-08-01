"""Drift monitor: the ops deploy checkout must stay a one-way mirror of origin/main.

Agents and humans have repeatedly committed inside the deploy checkout, so prod ran
code that never reached origin/main and a later deploy from a clean checkout silently
reverted it (2026-07-27 선례: skills/mail/SKILL.md v1.5.3->v1.5.5, 4 commits recovered).
``probe_checkout_mirrors_origin`` is the DETECT half of the permanent fix: it fails when
HEAD is not an ancestor of origin/main, or when a tracked file is modified.

The probe is shell, so it is exercised as shell. ``ssh``/``sudo`` stand-ins placed first on
PATH run the remote command against a throwaway git repo in ``tmp_path`` — no node, no
network, no dependence on this repository's own git state.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_HEALTHCHECK = _REPO / "automation" / "healthcheck.sh"
_MAIN_INVOCATION = 'main "$@"'


def _git(repo: Path, *args: str) -> None:
    _ = subprocess.run(
        ("git", "-C", str(repo), *args), check=True, capture_output=True, text=True
    )


def _mirror_checkout(tmp_path: Path) -> Path:
    """A deploy checkout in its healthy shape: HEAD == origin/main, nothing modified."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _ = subprocess.run(
        ("git", "init", "--bare", str(origin)), check=True, capture_output=True, text=True
    )
    checkout = tmp_path / "autophagy-agents"
    checkout.mkdir()
    _git(checkout, "init")
    _git(checkout, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(checkout, "config", "user.email", "probe@test.local")
    _git(checkout, "config", "user.name", "probe")
    _git(checkout, "config", "commit.gpgsign", "false")
    (checkout / "SKILL.md").write_text("version: 1.5.3\n", encoding="utf-8")
    _git(checkout, "add", "SKILL.md")
    _git(checkout, "commit", "-m", "deployed state")
    _git(checkout, "remote", "add", "origin", str(origin))
    _git(checkout, "push", "-u", "origin", "main")
    return checkout


def _fake_bin(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    remote_stub = fake_bin / ("s" + "sh")
    remote_stub.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\nexec bash -c "${*: -1}"\n', encoding="utf-8"
    )
    sudo = fake_bin / "sudo"
    sudo.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "while [[ $# -gt 0 ]]; do\n"
        '  case "$1" in\n'
        "    -n|-H) shift ;;\n"
        "    -u) shift 2 ;;\n"
        "    *) break ;;\n"
        "  esac\n"
        "done\n"
        'exec "$@"\n',
        encoding="utf-8",
    )
    remote_stub.chmod(0o755)
    sudo.chmod(0o755)
    return fake_bin


def _sourceable(tmp_path: Path) -> Path:
    """healthcheck.sh minus its top-level ``main "$@"`` — sourcing must not sweep the fleet."""
    lines = _HEALTHCHECK.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.strip() != _MAIN_INVOCATION]
    assert len(kept) == len(lines) - 1, f"expected exactly one `{_MAIN_INVOCATION}` line"
    sourceable = tmp_path / "healthcheck_sourceable.sh"
    sourceable.write_text("\n".join(kept) + "\n", encoding="utf-8")
    # healthcheck.sh sources checkout_mirror_probe.sh from its own directory, so the
    # sourceable copy needs the library beside it too.
    lib = _REPO / "automation" / "checkout_mirror_probe.sh"
    (tmp_path / "checkout_mirror_probe.sh").write_text(lib.read_text(encoding="utf-8"), encoding="utf-8")
    return sourceable


def _probe(
    tmp_path: Path, checkout: Path, *, with_ssh_sudo: bool = True
) -> subprocess.CompletedProcess[str]:
    script = (
        f'source "{_sourceable(tmp_path)}"\n'
        f'if probe_checkout_mirrors_origin "test-node" "ops" "{checkout}"; then\n'
        "  echo PROBE-PASS\n"
        "else\n"
        "  echo PROBE-FAIL\n"
        "  exit 1\n"
        "fi\n"
    )
    env = dict(os.environ)
    if with_ssh_sudo:
        path_prefix = f"{_fake_bin(tmp_path)}{os.pathsep}"
    else:
        path_prefix = f"{_ssh_free_path(tmp_path)}{os.pathsep}"
    env["PATH"] = f"{path_prefix}{env['PATH']}"
    env["HEALTHCHECK_LOG_DIR"] = str(tmp_path / "logs")
    env["HEALTHCHECK_HOST_A"] = "node-a"
    env["HEALTHCHECK_HOST_B"] = "node-b"
    env["HEALTHCHECK_SSH_USER"] = "ops"
    env["HEALTHCHECK_SSH_IDENTITY"] = ""
    env["HEALTHCHECK_DASHBOARD_AUTH_URL"] = "http://127.0.0.1:8800/"
    env["HEALTHCHECK_OPS_CHECKOUT"] = str(checkout)
    env["HEALTHCHECK_REPAIR_CLI"] = str(tmp_path / "repair_cli.py")
    env["HEALTHCHECK_MCP_COLLECTION"] = "fixture-collection"
    env["HEALTHCHECK_REPAIR_ACCOUNT"] = "ops"
    return subprocess.run(
        ("bash", "-c", script), capture_output=True, text=True, check=False, env=env
    )


def _ssh_free_path(tmp_path: Path) -> Path:
    """A PATH with real git but NO ssh/sudo — shadow them with a hard-deny stub."""
    deny = tmp_path / "nossh"
    deny.mkdir(exist_ok=True)
    for name in ("ssh", "sudo"):
        blocked = deny / name
        blocked.write_text(
            '#!/usr/bin/env bash\necho "'"'"'{}'"'"' must not be used by a local probe" >&2\nexit 97\n'.format(name),
            encoding="utf-8",
        )
        blocked.chmod(0o755)
    return deny


def _advance_origin(tmp_path: Path, checkout: Path) -> None:
    """Move the bare origin's main one commit ahead, leaving the checkout stale."""
    mover = tmp_path / "mover"
    _ = subprocess.run(
        ("git", "clone", "-b", "main", str(tmp_path / "origin.git"), str(mover)),
        check=True, capture_output=True, text=True,
    )
    _git(mover, "config", "user.email", "mover@test.local")
    _git(mover, "config", "user.name", "mover")
    _git(mover, "config", "commit.gpgsign", "false")
    (mover / "SKILL.md").write_text("version: 1.6.0\n", encoding="utf-8")
    _git(mover, "commit", "-am", "a commit only origin has")
    _git(mover, "push", "origin", "main")


def test_checkout_at_origin_main_passes(tmp_path: Path) -> None:
    checkout = _mirror_checkout(tmp_path)
    result = _probe(tmp_path, checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROBE-PASS" in result.stdout


def test_local_commit_ahead_of_origin_fails(tmp_path: Path) -> None:
    """The exact 2026-07-27 shape: prod holds a commit that origin/main has never seen."""
    checkout = _mirror_checkout(tmp_path)
    (checkout / "SKILL.md").write_text("version: 1.5.5\n", encoding="utf-8")
    _git(checkout, "commit", "-am", "learned in prod, never pushed")
    result = _probe(tmp_path, checkout)
    assert result.returncode == 1
    assert "PROBE-FAIL" in result.stdout


def test_modified_tracked_file_fails(tmp_path: Path) -> None:
    checkout = _mirror_checkout(tmp_path)
    (checkout / "SKILL.md").write_text("version: 1.5.5\n", encoding="utf-8")
    result = _probe(tmp_path, checkout)
    assert result.returncode == 1
    assert "PROBE-FAIL" in result.stdout


def test_untracked_files_alone_pass(tmp_path: Path) -> None:
    """``--untracked-files=no`` is deliberate: logs/ and caches are not drift."""
    checkout = _mirror_checkout(tmp_path)
    (checkout / "healthcheck-20260727T000000Z.log").write_text("noise\n", encoding="utf-8")
    result = _probe(tmp_path, checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROBE-PASS" in result.stdout


def test_behind_origin_fails(tmp_path: Path) -> None:
    """The gap the old probe was blind to: origin moved ahead, prod is stale.

    ``merge-base --is-ancestor HEAD origin/main`` SUCCEEDS when behind, and with no
    fetch the local ``origin/main`` ref is itself stale — so today's probe calls a
    behind checkout ``mirror-clean``. A live ``ls-remote`` is the only way to see it.
    """
    checkout = _mirror_checkout(tmp_path)
    _advance_origin(tmp_path, checkout)
    result = _probe(tmp_path, checkout)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "PROBE-FAIL" in result.stdout


def test_probe_runs_without_ssh_or_sudo(tmp_path: Path) -> None:
    checkout = _mirror_checkout(tmp_path)
    result = _probe(tmp_path, checkout, with_ssh_sudo=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROBE-PASS" in result.stdout


def test_unreachable_remote_degrades_not_fails(tmp_path: Path) -> None:
    """A network blip must not cry wolf: unknown-behind is not behind.

    A monitor that fails closed on an ``ls-remote`` timeout is the exact cry-wolf
    failure being fixed. The severe fault (ahead/dirty) is still caught fully offline.
    """
    checkout = _mirror_checkout(tmp_path)
    _git(checkout, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))
    result = _probe(tmp_path, checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROBE-PASS" in result.stdout
    assert "BEHIND-UNKNOWN" in (result.stdout + result.stderr)
