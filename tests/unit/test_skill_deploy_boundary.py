from __future__ import annotations

import subprocess
import shutil
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "automation" / "deploy-skill.sh"
BOOTSTRAP = ROOT / "automation" / "provision-readonly-skills.sh"
MEETING_SCENARIO = ROOT / "skills" / "meeting" / "scripts" / "scenario.sh"
REPORT_SCENARIO = ROOT / "skills" / "report" / "scripts" / "scenario.sh"
PROPOSAL_CLI = ROOT / "skills" / "proposal" / "scripts" / "proposal_cli.py"


def test_deploy_when_mounting_or_removing_then_uses_only_privileged_store_helper() -> None:
    # Given
    script = DEPLOY.read_text(encoding="utf-8")

    # When / Then
    assert "/usr/local/libexec/autophagy-install-skill install" in script
    assert "/usr/local/libexec/autophagy-install-skill remove" in script
    assert "mount_reviewed_skill" not in script
    assert 'rm -rf "\\$HOME/.hermes/skills/$SKILL"' not in script


def test_deploy_when_parsing_flags_then_accepts_approve_only_and_keeps_existing_arms() -> None:
    # Given
    script = DEPLOY.read_text(encoding="utf-8")

    # When / Then
    assert "REQUEST_ONLY=0 APPROVE_ONLY=0 FRESH=0 SANDBOX_ONLY=0 REMOVE=0" in script
    assert "--approve-only) APPROVE_ONLY=1 ;;" in script
    assert "--request-only) REQUEST_ONLY=1 ;;" in script
    assert "--sandbox-only) SANDBOX_ONLY=1 ;;" in script
    assert "--remove) REMOVE=1 ;;" in script
    assert "--approve-only" in script


def test_deploy_when_managed_activation_is_requested_then_parses_its_quarantine_dir() -> None:
    # Given
    script = DEPLOY.read_text(encoding="utf-8")

    # When / Then
    assert "ACTIVATE_MANAGED=0" in script
    assert "--activate-managed)" in script
    assert 'QUARANTINE_DIR="$2"' in script
    assert "shift 2" in script


def test_deploy_when_managed_name_would_mount_plainly_then_blocks_before_stage_one() -> None:
    # Given
    script = DEPLOY.read_text(encoding="utf-8")

    # When / Then
    guard = (
        'if [[ "$ACTIVATE_MANAGED" == 0 && "$APPROVE_ONLY" == 0 '
        '&& "$SANDBOX_ONLY" == 0 && "$REQUEST_ONLY" == 0 '
        '&& "$SKILL" == managed-* ]]; then'
    )
    assert guard in script
    assert 'die "MANAGED-BLOCK: mounting a managed skill requires --activate-managed"' in script


def test_deploy_when_managed_activation_quarantine_is_missing_then_fails_before_remote_stages(
    tmp_path: Path,
) -> None:
    # Given
    missing_quarantine = tmp_path / "missing"

    # When
    completed = subprocess.run(
        ["bash", str(DEPLOY), "managed-demo", "--activate-managed", str(missing_quarantine)],
        capture_output=True,
        text=True,
        check=False,
    )

    # Then
    assert completed.returncode != 0
    assert "MANAGED-BLOCK: quarantine directory missing" in completed.stderr


def test_deploy_when_managed_activation_requests_approval_then_forwards_provenance_file() -> None:
    # Given
    script = DEPLOY.read_text(encoding="utf-8")

    # When / Then
    assert 'MANAGED_REQUEST_ARGS=(--provenance-file "$MANAGED_PROVENANCE_REMOTE")' in script
    assert script.count('"${MANAGED_REQUEST_ARGS[@]}"') == 4
    assert script.count('check_with_attestation_refresh "$') == 2
    for key in ("publisher", "tag", "release_sequence", "manifest_sha256"):
        assert f'"{key}"' in script


def test_deploy_when_managed_activation_mounts_then_uses_managed_store_verb() -> None:
    # Given
    script = DEPLOY.read_text(encoding="utf-8")

    # When / Then
    assert "install_managed_skill() {" in script
    assert "autophagy-install-skill install-managed --publisher" in script
    assert 'install_managed_skill "$SRC_DIR" "$MANAGED_PUBLISHER" "$SKILL" "$DIGEST"' in script


def test_deploy_when_skill_names_overlap_then_checks_both_live_namespace_collisions() -> None:
    # Given
    script = DEPLOY.read_text(encoding="utf-8")

    # When / Then
    assert 'readlink "$STORE_ROOT/live/$MANAGED_BASE"' in script
    assert 'readlink "$STORE_ROOT/live/managed-$SKILL"' in script
    assert "COLLISION-BLOCK" in script


def test_deploy_when_activating_quarantine_then_recomputes_manifest_bound_digest() -> None:
    # Given
    script = DEPLOY.read_text(encoding="utf-8")

    # When / Then
    assert "from automation.managed_skills.manifest import manifest_digest, parse_manifest" in script
    assert 'QUARANTINE_DIGEST="$(skill_digest "$MANAGED_SKILL_DIR")"' in script
    assert '[[ "$QUARANTINE_DIGEST" == "$MANAGED_DIGEST" ]]' in script


def test_deploy_when_approval_grants_then_exits_before_stage_four_with_evidence() -> None:
    # Given
    script = DEPLOY.read_text(encoding="utf-8")

    # When
    approval_granted = script.index('log "approval GRANTED (logged to approvals.jsonl)"')
    approve_only_exit = script.index("if [[ \"$APPROVE_ONLY\" == 1 ]]; then")
    evidence_output = script.index("printf '%s:%s\\n' \"$MESSAGE_ID\" \"$DEPLOY_NONCE\"")
    stage_four = script.index("# ---------- stage 4: recheck reviewed current hash, then mount its artifact ----------")

    # Then
    assert approval_granted < approve_only_exit < evidence_output < stage_four


@pytest.mark.parametrize(
    "required_text",
    (
        "^[a-z0-9][a-z0-9-]{1,40}$",
        'SRC_DIR="${SKILL_SRC_DIR:-$REPO_ROOT/skills/$SKILL}"',
        "autophagy-install-skill install --skill",
        "autophagy-install-skill remove --skill",
    ),
    ids=("skill-name-regex", "source-override", "install-helper", "remove-helper"),
)
def test_deploy_when_current_boundary_contract_is_read_then_required_text_is_present(
    required_text: str,
) -> None:
    # Given: the current deploy script text.
    script = DEPLOY.read_text(encoding="utf-8")

    # When / Then: each managed-skill prerequisite is checked statically.
    assert required_text in script


def test_bootstrap_when_activated_then_installs_read_only_persistent_bind_mount() -> None:
    # Given
    script = BOOTSTRAP.read_text(encoding="utf-8")

    # When / Then
    assert "install -m 0755 -o root -g root" in script
    assert "/usr/local/libexec/autophagy-install-skill" in script
    assert "bind,ro,nosuid,nodev" in script
    assert "visudo -cf" in script
    assert "mountpoint -q" in script


def test_sudoers_when_rendered_then_grants_only_root_owned_helper(tmp_path: Path) -> None:
    # Given
    template = (ROOT / "automation" / "sudoers.d" / "autophagy-skill-store").read_text(encoding="utf-8")
    assert "%%TEMPLATE_NOT_RENDERED%%" in template
    rendered = template.replace("%%DEPLOY_USER%%", "test-deployer").replace(
        "%%TEMPLATE_NOT_RENDERED%%", ""
    )
    destination = tmp_path / "autophagy-skill-store"
    destination.write_text(rendered, encoding="utf-8")

    # When / Then
    rules = [
        line
        for line in destination.read_text(encoding="utf-8").splitlines()
        if line.startswith("test-deployer ")
    ]
    assert len(rules) == 3
    assert all(rule.endswith("/usr/local/libexec/autophagy-install-skill install --skill * --hash *") for rule in rules[:1])
    assert all(rule.endswith("/usr/local/libexec/autophagy-install-skill install-managed --publisher * --skill * --hash *") for rule in rules[1:2])
    assert all(rule.endswith("/usr/local/libexec/autophagy-install-skill remove --skill *") for rule in rules[2:])


def test_bootstrap_when_hermes_needs_hub_state_then_mounts_only_hidden_cache_writable() -> None:
    # Given
    script = BOOTSTRAP.read_text(encoding="utf-8")

    # When / Then
    assert 'HUB_STATE="/home/agent/.hermes/skill-hub-state"' in script
    assert 'HUB_TARGET="$TARGET/.hub"' in script
    assert "bind,rw,nosuid,nodev,noexec" in script
    assert 'mountpoint -q "$HUB_TARGET"' in script


def test_bootstrap_when_fstab_changes_then_reloads_systemd_mount_units() -> None:
    # Given
    script = BOOTSTRAP.read_text(encoding="utf-8")

    # When / Then
    assert "systemctl daemon-reload" in script


def test_meeting_compile_when_skill_is_read_only_then_uses_temporary_pycache() -> None:
    # Given
    script = MEETING_SCENARIO.read_text(encoding="utf-8")

    # When / Then
    assert 'export PYTHONPYCACHEPREFIX="$work/pycache"' in script


def test_report_isolated_runner_when_mounted_then_adds_skill_package_parent() -> None:
    # Given
    script = REPORT_SCENARIO.read_text(encoding="utf-8")

    # When / Then
    assert "Path(script_dir).parents[1]" in script


def test_proposal_cli_when_invoked_through_release_symlink_then_resolves_its_package(
    tmp_path: Path,
) -> None:
    # Given
    release = tmp_path / "releases" / "digest"
    _ = shutil.copytree(PROPOSAL_CLI.parents[1], release)
    mounted = tmp_path / "skills" / "proposal"
    mounted.parent.mkdir()
    mounted.symlink_to(release, target_is_directory=True)

    # When
    completed = subprocess.run(
        [sys.executable, "-I", str(mounted / "scripts" / "proposal_cli.py"), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Then
    assert completed.returncode == 0, completed.stderr
