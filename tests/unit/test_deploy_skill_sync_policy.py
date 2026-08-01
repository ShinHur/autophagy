from __future__ import annotations

from pathlib import Path
from tests.unit._synthetic import synthetic_env


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "automation" / "deploy-skill.sh"
DEPLOY_ROOT = synthetic_env()["AUTOPHAGY_DEPLOY_ROOT"]
RELEASE_CURRENT = str(Path(DEPLOY_ROOT).with_name("autophagy-agent-current"))
SERVICE_ROOT = str(Path(DEPLOY_ROOT).parent)


def test_deploy_when_stage3_starts_then_syncs_ops_checkout_before_request_and_attest() -> None:
    # Given
    script = DEPLOY.read_text(encoding="utf-8")

    # When / Then
    def_idx = script.index("sync_ops_checkout_for_peer_attest() {")
    call_idx = script.index("\nsync_ops_checkout_for_peer_attest\n")
    assert def_idx < call_idx
    assert call_idx < script.index('if [[ -n "${APPROVAL_MESSAGE_ID:-}" ]]')
    assert call_idx < script.index('request --skill "$SKILL"')
    assert call_idx < script.index('peer_attest "$SKILL" "$DIGEST"', call_idx)


def test_deploy_sync_when_pulled_then_verifies_verifier_file_hashes_via_ops_account() -> None:
    # Given
    script = DEPLOY.read_text(encoding="utf-8")

    # When / Then
    def_idx = script.index("sync_ops_checkout_for_peer_attest() {")
    body = script[def_idx : script.index("\n}", def_idx)]
    assert "run_as ops" in body
    assert 'git -C $MIRROR_CHECKOUT pull --ff-only' in body
    assert "rev-parse --is-inside-work-tree" in body
    assert "status --porcelain" in body
    assert "sha256sum" in body
    for fname in (
        "peer_attest.py",
        "peer_attestation.py",
        "skill_review.py",
        "deploy_execution_lock.py",
        "interop/approval_lease.py",
    ):
        assert fname in body


def test_deploy_sync_when_ops_checkout_unhealthy_then_fails_closed_with_clear_messages() -> None:
    # Given
    script = DEPLOY.read_text(encoding="utf-8")

    # When / Then
    def_idx = script.index("sync_ops_checkout_for_peer_attest() {")
    body = script[def_idx : script.index("\n}", def_idx)]
    assert "SYNC-BLOCK: $MIRROR_CHECKOUT is not a git checkout" in body
    assert "SYNC-BLOCK: ops checkout is dirty (local modifications present)" in body
    assert "SYNC-BLOCK: ff-only pull failed on ops checkout" in body
    assert "differs between local repo and ops checkout" in body


# --- DG-4 W3.D: deploy-skill.sh becomes runtime-root aware, fallback-safe ---

def test_deploy_sources_the_runtime_root_resolver() -> None:
    # The shell runtime-root resolver is available so paths are not bare literals.
    script = DEPLOY.read_text(encoding="utf-8")
    assert "runtime_root.sh" in script
    assert "autophagy_runtime_root" in script


def test_deploy_prefers_release_current_when_present() -> None:
    # When the release runtime exists, the sync path converges a pinned snapshot
    # release and flips current BEFORE peer attestation, instead of ff-pulling the
    # mutable mirror. A parallel session's dirty mirror can no longer block deploy.
    script = DEPLOY.read_text(encoding="utf-8")
    def_idx = script.index("sync_ops_checkout_for_peer_attest() {")
    body = script[def_idx : script.index("\n}", def_idx)]
    assert 'RELEASE_CURRENT="$(dirname "$MIRROR_CHECKOUT")/autophagy-agent-current"' in script
    assert "$RELEASE_CURRENT" in body
    assert "converge-release-runtime.sh" in body
    # the converge helper is where the snapshot primitive is invoked
    converge = (ROOT / "automation" / "converge-release-runtime.sh").read_text(encoding="utf-8")
    assert "origin_snapshot" in converge
    assert "autophagy-install-release" in converge


def test_deploy_falls_back_to_ff_pull_when_current_absent() -> None:
    # Backwards-compatible: with no current symlink, the existing ff-pull path is
    # preserved verbatim, so merging PR-A is a live no-op until the DG-5 flip.
    script = DEPLOY.read_text(encoding="utf-8")
    def_idx = script.index("sync_ops_checkout_for_peer_attest() {")
    body = script[def_idx : script.index("\n}", def_idx)]
    assert 'git -C $MIRROR_CHECKOUT pull --ff-only' in body
    assert "SYNC-BLOCK: ff-only pull failed on ops checkout" in body


# --- DG-5: trust-critical exec paths resolve the runtime root NODE-SIDE ---

def test_peer_attest_and_lock_run_from_a_node_resolved_runtime_root() -> None:
    # peer_attest / execution-lock / chmod run via `run_as <acct>` ON THE NODE, so
    # the runtime root must be resolved inside that node-side shell, not interpolated
    # from the workstation-resolved $RUNTIME_ROOT (which stats a node path on the
    # wrong host). A node-side helper resolves current-else-mirror in the run_as body.
    script = DEPLOY.read_text(encoding="utf-8")
    # a node-side resolver snippet exists and is used by the trust-critical run_as calls
    assert "node_runtime_root" in script
    # the peer_attest invocation no longer hardcodes the mirror python path
    peer_line = next(line for line in script.splitlines() if "peer_attest.py" in line and "--skill" in line)
    assert f"{DEPLOY_ROOT}/automation/peer_attest.py" not in peer_line
    assert "node_runtime_root" in peer_line
    # the execution lock no longer hardcodes the mirror
    lock_line = next(line for line in script.splitlines() if "deploy_execution_lock.py" in line and "--skill" in line)
    assert f"PYTHONPATH={DEPLOY_ROOT} " not in lock_line
    assert f"{DEPLOY_ROOT}/automation/deploy_execution_lock.py" not in lock_line
    assert "node_runtime_root" in lock_line


def test_node_runtime_root_helper_resolves_current_else_mirror() -> None:
    # The node-side helper must prefer the release runtime when it exists,
    # else fall back to the mirror (a live no-op until the DG-5 flip).
    script = DEPLOY.read_text(encoding="utf-8")
    def_idx = script.index("node_runtime_root()")
    body = script[def_idx : script.index("\n}", def_idx)]
    assert "$RELEASE_CURRENT" in body
    assert "$MIRROR_CHECKOUT" in body


def test_converge_helper_uses_canonical_paths_and_sudo_install() -> None:
    # DG-5 path-convention fix: converge installs to the canonical release layout
    # via `sudo -n` (ops running a root-owned helper does not gain root), and the
    # read-only `current --verify` runs without sudo.
    converge = (ROOT / "automation" / "converge-release-runtime.sh").read_text(encoding="utf-8")
    # the privileged install line (command, not a comment) carries sudo -n
    cmd_lines = [line for line in converge.splitlines() if not line.lstrip().startswith("#")]
    install_line = next(line for line in cmd_lines if "install --sha" in line)
    assert "sudo -n" in install_line
    # the read-only verify line does NOT need sudo
    verify_line = next(line for line in cmd_lines if "current --verify" in line)
    assert "sudo" not in verify_line
    # The configured store-root parent supplies canonical release basenames.
    assert "RELEASE_STORE_PARENT" in converge
    assert "STORE_PARENT=" in converge
    # release_store.py owns the canonical basenames (not a bare literal here)
    rs = (ROOT / "automation" / "release_store.py").read_text(encoding="utf-8")
    assert '_RELEASES_BASENAME: Final = "autophagy-agent-releases"' in rs
    assert '_CURRENT_BASENAME: Final = "autophagy-agent-current"' in rs


def test_release_store_never_uses_the_generic_layout_names() -> None:
    # Lock the 2026-07-31 rollout bug shut: no bare store_root/"releases" or
    # store_root/"current" that would land in the generic layout.
    rs = (ROOT / "automation" / "release_store.py").read_text(encoding="utf-8")
    assert 'store_root / "releases"' not in rs
    assert 'store_root / "current"' not in rs


# --- DG-6: the converger becomes safe to call from a landing ------------------


def test_converge_honours_an_explicitly_pinned_sha() -> None:
    # land.sh must converge the runtime to the sha IT pushed. Left to re-read
    # origin the converger would install whatever landed most recently instead,
    # so the caller's post-condition would be checking someone else's landing.
    converge = (ROOT / "automation" / "converge-release-runtime.sh").read_text(encoding="utf-8")
    assert "RELEASE_EXPECTED_SHA" in converge
    cmd_lines = [line for line in converge.splitlines() if not line.lstrip().startswith("#")]
    ls_remote = next(line for line in cmd_lines if "ls-remote" in line)
    # origin is only consulted when no sha was pinned
    assert "RELEASE_EXPECTED_SHA" in ls_remote or any(
        "RELEASE_EXPECTED_SHA" in line and "ls-remote" not in line for line in cmd_lines
    )


def test_converge_sources_the_snapshot_primitive_from_its_own_tree() -> None:
    # DG-6 downgrades a dirty mirror to a warning; that is only sound while we
    # stop EXECUTING the mirror's shell. Sourcing the snapshot primitive out of
    # $MIRROR would run a parallel session's uncommitted code as ops.
    converge = (ROOT / "automation" / "converge-release-runtime.sh").read_text(encoding="utf-8")
    source_line = next(
        line for line in converge.splitlines()
        if line.lstrip().startswith("source") and "origin_snapshot.sh" in line
    )
    assert "$MIRROR" not in source_line
    assert "BASH_SOURCE" in source_line


def test_converge_serializes_the_install_and_flip() -> None:
    # `current` is flipped by both land.sh and deploy-skill.sh. origin_snapshot's
    # own lock is released before the command runs, so without a shared lock a
    # slow older convergence can flip the runtime BACKWARDS over a newer one.
    converge = (ROOT / "automation" / "converge-release-runtime.sh").read_text(encoding="utf-8")
    assert "flock" in converge
    # ...on a path that does not move with the caller's environment: a lock two
    # callers resolve differently is not a lock.
    lock_line = next(line for line in converge.splitlines() if line.startswith("LOCK="))
    assert "TMPDIR" not in lock_line


def test_deploy_runs_the_converger_from_the_runtime_root_not_the_mirror() -> None:
    script = DEPLOY.read_text(encoding="utf-8")
    def_idx = script.index("sync_ops_checkout_for_peer_attest() {")
    body = script[def_idx : script.index("\n}", def_idx)]
    converge_line = next(line for line in body.splitlines() if "converge-release-runtime.sh" in line)
    assert f"{DEPLOY_ROOT}/automation/converge-release-runtime.sh" not in converge_line
    assert "$RELEASE_CURRENT" in converge_line
