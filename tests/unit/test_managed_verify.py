from __future__ import annotations

import json
import subprocess
import tarfile
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from automation.managed_skills.manifest import manifest_digest, parse_manifest
from automation.managed_sync import verify as managed_verify
from automation.managed_sync.state import SkillState
from automation.skill_review import skill_digest


@dataclass(frozen=True, slots=True)
class VerifyConfig:
    allowed_signers: Path
    mirror_dir: Path


@dataclass(frozen=True, slots=True)
class CommandResponse:
    returncode: int
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True, slots=True)
class ManifestInput:
    skill_sha256: str
    skill: str = "managed-demo"
    release_sequence: int = 2
    previous_sha256: str | None = "b" * 64
    revoked_digests: tuple[str, ...] = ()
    source_commit: str | None = "a" * 40


@dataclass(frozen=True, slots=True)
class VerifyFixture:
    mirror: Path
    config: VerifyConfig
    state: SkillState
    tag: str
    manifest_text: str
    tag_message: str
    archive_root: Path
    signature: CommandResponse


class FakeGit:
    def __init__(self, fixture: VerifyFixture) -> None:
        self.fixture: VerifyFixture = fixture
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        args: list[str],
        /,
        *,
        env: dict[str, str],
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del env, capture_output, text, timeout
        self.calls.append(tuple(args))
        if "verify-tag" in args:
            return self._result(args, self.fixture.signature)
        if "show" in args:
            return self._result(args, CommandResponse(0, self.fixture.manifest_text))
        if "tag" in args:
            return self._result(args, CommandResponse(0, self.fixture.tag_message))
        if "archive" in args:
            archive_path = Path(args[args.index("--output") + 1])
            self._write_archive(archive_path)
            return self._result(args, CommandResponse(0))
        raise AssertionError(f"unexpected git command: {args}")

    @staticmethod
    def _result(args: list[str], response: CommandResponse) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, response.returncode, response.stdout, response.stderr)

    def _write_archive(self, archive_path: Path) -> None:
        with tarfile.open(archive_path, "w") as archive:
            for source in sorted(self.fixture.archive_root.rglob("*")):
                if source.is_file():
                    archive.add(source, arcname=source.relative_to(self.fixture.archive_root))


def _manifest_text(input: ManifestInput) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "publisher": "publisher",
            "skill": input.skill,
            "release_sequence": input.release_sequence,
            "source_commit": input.source_commit,
            "skill_sha256": input.skill_sha256,
            "previous_sha256": input.previous_sha256,
            "compatibility": "any",
            "breaking": False,
            "revoked_digests": list(input.revoked_digests),
            "changelog": "test release",
        }
    )


@pytest.fixture
def verified_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> VerifyFixture:
    skill_dir = tmp_path / "source" / "skills" / "managed-demo"
    skill_dir.mkdir(parents=True)
    _ = (skill_dir / "SKILL.md").write_text("---\nname: managed-demo\n---\n", encoding="utf-8")
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    scenario = scripts_dir / "scenario.sh"
    _ = scenario.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    scenario.chmod(0o755)
    manifest_text = _manifest_text(ManifestInput(skill_sha256=skill_digest(skill_dir)))
    signers = tmp_path / "allowed_signers"
    principal = "publisher@example.invalid"
    monkeypatch.setenv("MANAGED_PUBLISHER_PRINCIPAL", principal)
    _ = signers.write_text(principal + "\n", encoding="utf-8")
    return VerifyFixture(
        mirror=tmp_path / "mirror",
        config=VerifyConfig(allowed_signers=signers, mirror_dir=tmp_path / "mirror"),
        state=SkillState(highest_sequence=1, last_verified_digest="b" * 64),
        tag="managed-demo/v2",
        manifest_text=manifest_text,
        tag_message=f"manifest_sha256:{manifest_digest(parse_manifest(manifest_text))}\n",
        archive_root=tmp_path / "source",
        signature=CommandResponse(
            0,
            stderr=f'Good "git" signature for {principal} with ED25519 key SHA256:test',
        ),
    )


def _verify(
    fixture: VerifyFixture, *, allow_rollback: bool = False
) -> tuple[managed_verify.VerifiedRelease, FakeGit]:
    runner = FakeGit(fixture)
    release = managed_verify.verify_release(
        fixture.mirror,
        fixture.tag,
        fixture.config,
        fixture.state,
        runner,
        allow_rollback=allow_rollback,
    )
    return release, runner


def _assert_failure(fixture: VerifyFixture, prefix: str, *, allow_rollback: bool = False) -> None:
    with pytest.raises(managed_verify.ManagedVerifyError, match=rf"^{prefix}:"):
        _ = _verify(fixture, allow_rollback=allow_rollback)


def _rollback_fixture(fixture: VerifyFixture) -> VerifyFixture:
    digest = parse_manifest(fixture.manifest_text).skill_sha256
    manifest_text = _manifest_text(ManifestInput(digest, release_sequence=3))
    return replace(
        fixture,
        state=SkillState(highest_sequence=5, last_verified_digest="a" * 64),
        tag="managed-demo/v3",
        manifest_text=manifest_text,
        tag_message=f"manifest_sha256:{manifest_digest(parse_manifest(manifest_text))}",
    )


def test_verify_release_when_every_check_passes_then_returns_verified_release(
    verified_fixture: VerifyFixture,
) -> None:
    release, _ = _verify(verified_fixture)

    assert release.skill == "managed-demo"
    assert release.sequence == 2
    assert release.digest == parse_manifest(verified_fixture.manifest_text).skill_sha256
    assert release.tree_path.is_dir()


def test_verify_release_when_rollback_signature_is_invalid_then_fails_closed(verified_fixture: VerifyFixture) -> None:
    fixture = _rollback_fixture(verified_fixture)
    _assert_failure(replace(fixture, signature=CommandResponse(1, stderr="invalid")), "BAD-SIGNATURE", allow_rollback=True)


def test_verify_release_when_rollback_principal_is_wrong_then_fails_closed(verified_fixture: VerifyFixture) -> None:
    wrong_principal = CommandResponse(
        0,
        stderr='Good "git" signature for other@autophagy with ED25519 key SHA256:test',
    )
    _assert_failure(replace(_rollback_fixture(verified_fixture), signature=wrong_principal), "WRONG-PRINCIPAL", allow_rollback=True)


def test_verify_release_when_tag_manifest_digest_is_swapped_then_fails_closed(
    verified_fixture: VerifyFixture,
) -> None:
    _assert_failure(replace(verified_fixture, tag_message="manifest_sha256:" + "a" * 64), "MANIFEST-BINDING")


def test_verify_release_when_manifest_is_malformed_then_fails_closed(verified_fixture: VerifyFixture) -> None:
    _assert_failure(replace(verified_fixture, manifest_text="{"), "MANIFEST-SCHEMA")


def test_verify_release_when_tag_name_disagrees_with_manifest_then_fails_closed(
    verified_fixture: VerifyFixture,
) -> None:
    manifest_text = _manifest_text(ManifestInput(parse_manifest(verified_fixture.manifest_text).skill_sha256, skill="managed-other"))
    fixture = replace(
        verified_fixture,
        manifest_text=manifest_text,
        tag_message=f"manifest_sha256:{manifest_digest(parse_manifest(manifest_text))}",
    )
    _assert_failure(fixture, "TAG-MISMATCH")


def test_verify_release_when_sequence_replays_then_fails_closed(verified_fixture: VerifyFixture) -> None:
    _assert_failure(replace(verified_fixture, state=SkillState(highest_sequence=2, last_verified_digest="b" * 64)), "SEQUENCE-REPLAY")


def test_verify_release_when_previous_digest_chain_breaks_then_fails_closed(
    verified_fixture: VerifyFixture,
) -> None:
    fixture = replace(_rollback_fixture(verified_fixture), state=SkillState(highest_sequence=2, last_verified_digest="a" * 64))
    _assert_failure(fixture, "CHAIN-BREAK")


def test_verify_release_when_rollback_archive_digest_changes_then_fails_closed(verified_fixture: VerifyFixture) -> None:
    _ = (verified_fixture.archive_root / "skills" / "managed-demo" / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    _assert_failure(_rollback_fixture(verified_fixture), "DIGEST-MISMATCH", allow_rollback=True)


def test_verify_release_when_state_revokes_digest_then_fails_closed(verified_fixture: VerifyFixture) -> None:
    digest = parse_manifest(verified_fixture.manifest_text).skill_sha256
    _assert_failure(replace(verified_fixture, state=SkillState(1, "b" * 64, revoked_digests=(digest,))), "REVOKED")


def test_verify_release_when_rollback_manifest_revokes_digest_then_fails_closed(verified_fixture: VerifyFixture) -> None:
    fixture = _rollback_fixture(verified_fixture)
    digest = parse_manifest(fixture.manifest_text).skill_sha256
    manifest_text = _manifest_text(ManifestInput(digest, release_sequence=3, revoked_digests=(digest,)))
    fixture = replace(
        fixture,
        manifest_text=manifest_text,
        tag_message=f"manifest_sha256:{manifest_digest(parse_manifest(manifest_text))}",
    )
    _assert_failure(fixture, "REVOKED", allow_rollback=True)


def test_verify_release_when_rollback_is_explicit_then_accepts_replayed_sequence(
    verified_fixture: VerifyFixture,
) -> None:
    release, _ = _verify(_rollback_fixture(verified_fixture), allow_rollback=True)

    assert release.sequence == 3


def test_verify_release_when_source_commit_differs_then_accepts_provenance_only(
    verified_fixture: VerifyFixture,
) -> None:
    release, _ = _verify(verified_fixture)

    assert release.manifest.source_commit == "a" * 40


def test_verify_release_when_reading_content_then_uses_only_tag_bound_git_commands(
    verified_fixture: VerifyFixture,
) -> None:
    _, runner = _verify(verified_fixture)
    manifest_ref = f"{verified_fixture.tag}:manifests/managed-demo.json"

    assert ("git", "-C", str(verified_fixture.mirror), "show", manifest_ref) in runner.calls
    assert any("archive" in call and verified_fixture.tag in call for call in runner.calls)


def test_verify_release_when_signature_fails_then_never_creates_tree_directory(
    verified_fixture: VerifyFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tree_dir = tmp_path / "tree-would-land-here"

    def fake_mkdtemp(_prefix: str) -> str:
        return str(tree_dir)

    monkeypatch.setattr("automation.managed_sync.verify.tempfile.mkdtemp", fake_mkdtemp)

    _assert_failure(replace(verified_fixture, signature=CommandResponse(1, stderr="invalid")), "BAD-SIGNATURE")

    assert not tree_dir.exists()


def test_verify_release_when_tree_extracted_then_owner_executable_bit_is_preserved(
    verified_fixture: VerifyFixture,
) -> None:
    release, _ = _verify(verified_fixture)

    script = release.tree_path / "scripts" / "scenario.sh"
    assert (script.stat().st_mode & 0o100) != 0


def test_verify_release_when_tree_extracted_then_non_executable_file_stays_non_executable(
    verified_fixture: VerifyFixture,
) -> None:
    release, _ = _verify(verified_fixture)

    skill_md = release.tree_path / "SKILL.md"
    assert (skill_md.stat().st_mode & 0o111) == 0


def test_verify_release_when_member_carries_setuid_then_data_filter_strips_it(
    verified_fixture: VerifyFixture,
) -> None:
    source_script = verified_fixture.archive_root / "skills" / "managed-demo" / "scripts" / "scenario.sh"
    source_script.chmod(0o4755)
    assert (source_script.stat().st_mode & 0o4000) != 0

    release, _ = _verify(verified_fixture)

    mode = (release.tree_path / "scripts" / "scenario.sh").stat().st_mode
    assert (mode & 0o4000) == 0
    assert (mode & 0o100) != 0
