"""Immutable release store: install a verified origin/main tree by value under
the configured release-store root and atomically flip its current symlink.

WHY (2026-07-31): the runtime must not live in a mutable, parallel-session-dirty
checkout. release_store installs a by-value copy of one pinned sha, makes it
root-owned and read-only (so peer_attest's tamper guard passes), and flips a
stable `current` symlink atomically. Runtime reads `current`; the resident
checkout becomes a drift-observation mirror only.

Mirrors the proven skill_store.py idioms (_make_read_only, _publish_live_link,
_member_parts, _require_root). Hermetic: a fake store root under tmp_path, a
tar.gz built in-process; no node, no root.
"""
from __future__ import annotations

import io
import subprocess
import sys
import tarfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_STORE = _REPO / "automation" / "release_store.py"
_SHA = "a" * 40
_OTHER_SHA = "b" * 40


def _tar_gz(files: dict[str, str], *, unsafe: str | None = None, self_dir: bool = False) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if self_dir:
            # What `tar -C <dir> ... .` actually emits: a top-level "." directory
            # member (and sometimes "./"). converge-release-runtime.sh does exactly
            # this, so the store must accept it, not reject it as unsafe.
            info = tarfile.TarInfo(".")
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            tar.addfile(info)
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
        if unsafe is not None:
            info = tarfile.TarInfo(unsafe)
            info.size = 0
            tar.addfile(info, io.BytesIO(b""))
    return buf.getvalue()


def _install(
    store_root: Path, sha: str, archive: bytes, *, verb: str = "install"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(_STORE), verb, "--sha", sha, "--store-root", str(store_root)),
        input=archive, capture_output=True, check=False,
    )


def _install_ok(store_root: Path, sha: str, files: dict[str, str] | None = None) -> None:
    payload = files if files is not None else {"automation/peer_attest.py": "x\n", "seed.txt": "s\n"}
    result = _install(store_root, sha, _tar_gz(payload))
    assert result.returncode == 0, result.stderr.decode()


# 2.1 install creates an immutable release and flips current -----------------

def test_install_creates_immutable_release_and_flips_current(tmp_path: Path) -> None:
    _install_ok(tmp_path, _SHA)
    release = tmp_path / "autophagy-agent-releases" / _SHA
    current = tmp_path / "autophagy-agent-current"
    assert release.is_dir()
    assert (release.stat().st_mode & 0o777) == 0o555
    a_file = release / "seed.txt"
    assert (a_file.stat().st_mode & 0o777) == 0o444
    assert (release / ".origin-sha").read_text(encoding="utf-8").strip() == _SHA
    assert current.is_symlink()
    assert current.resolve() == release.resolve()
    # the legacy generic layout must NOT be created (the 2026-07-31 rollout bug)
    assert not (tmp_path / "releases").exists()
    assert not (tmp_path / "current").exists()


# 2.3 atomic flip never clobbers a non-symlink current -----------------------

def test_flip_is_atomic_and_never_clobbers_a_non_symlink(tmp_path: Path) -> None:
    real_dir = tmp_path / "autophagy-agent-current"
    real_dir.mkdir()
    (real_dir / "precious.txt").write_text("do not delete\n", encoding="utf-8")
    result = _install(tmp_path, _SHA, _tar_gz({"seed.txt": "s\n"}))
    assert result.returncode != 0
    assert "RELEASE-STORE-BLOCK" in result.stderr.decode()
    assert (real_dir / "precious.txt").exists()  # the real dir survived


# 2.4 reinstalling the same sha is idempotent --------------------------------

def test_reinstall_same_sha_is_idempotent(tmp_path: Path) -> None:
    _install_ok(tmp_path, _SHA)
    release = tmp_path / "autophagy-agent-releases" / _SHA
    inode_before = release.stat().st_ino
    _install_ok(tmp_path, _SHA)
    assert release.stat().st_ino == inode_before  # same release dir, not replaced
    assert (tmp_path / "autophagy-agent-current").resolve() == release.resolve()
    assert not (tmp_path / "autophagy-agent-releases" / ".staging").exists()  # no residue


def test_install_accepts_a_tar_dot_self_directory_member(tmp_path: Path) -> None:
    # `tar -C <dir> ... .` (exactly what converge-release-runtime.sh runs) emits a
    # top-level "." directory member. The store must accept it, not RELEASE-STORE-BLOCK.
    result = _install(
        tmp_path, _SHA, _tar_gz({"automation/peer_attest.py": "x\n"}, self_dir=True)
    )
    assert result.returncode == 0, result.stderr.decode()
    release = tmp_path / "autophagy-agent-releases" / _SHA
    assert (release / "automation" / "peer_attest.py").read_text(encoding="utf-8") == "x\n"
    assert (tmp_path / "autophagy-agent-current").resolve() == release.resolve()


# 2.5 validation: sha shape and unsafe archive paths -------------------------

def test_sha_must_be_hex(tmp_path: Path) -> None:
    result = _install(tmp_path, "not-a-sha", _tar_gz({"seed.txt": "s\n"}))
    assert result.returncode != 0
    assert "RELEASE-STORE-BLOCK" in result.stderr.decode()


def test_unsafe_archive_paths_rejected(tmp_path: Path) -> None:
    for bad in ("../escape.txt", "/abs.txt", "a/../../b.txt"):
        result = _install(tmp_path, _SHA, _tar_gz({"seed.txt": "s\n"}, unsafe=bad))
        assert result.returncode != 0, bad
        assert "RELEASE-STORE-BLOCK" in result.stderr.decode()
    assert not (tmp_path / "autophagy-agent-releases" / _SHA).exists()  # nothing installed


# 2.6 the installed tree must not be group/other writable (peer-attest precond)

def test_release_tree_is_not_group_or_other_writable(tmp_path: Path) -> None:
    # peer_attest._find_tamperable_path rejects any entry with mode & 0o022 set;
    # the release store must produce a tree that passes that supply-chain guard.
    _install_ok(tmp_path, _SHA, {"automation/a.py": "1\n", "skills/mail/b.py": "2\n"})
    release = tmp_path / "autophagy-agent-releases" / _SHA
    for path in (release, *release.rglob("*")):
        assert (path.stat().st_mode & 0o022) == 0, path


# 2.8 collision C2: bootstrap-accounts.sh must be untouched by this work ------

def test_bootstrap_accounts_is_untouched(tmp_path: Path) -> None:  # noqa: ARG001
    head = subprocess.run(
        ("git", "-C", str(_REPO), "rev-parse", "origin/main:automation/bootstrap-accounts.sh"),
        capture_output=True, text=True, check=False,
    )
    work = subprocess.run(
        ("git", "-C", str(_REPO), "hash-object", "automation/bootstrap-accounts.sh"),
        capture_output=True, text=True, check=False,
    )
    if head.returncode == 0 and work.returncode == 0:
        assert head.stdout.strip() == work.stdout.strip(), "C2: bootstrap-accounts.sh diverged from origin/main"
