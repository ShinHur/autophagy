from __future__ import annotations

import dataclasses

import pytest

from automation.managed_skills.announce import announce_release
from automation.managed_skills.manifest import ManagedManifest


@dataclasses.dataclass
class FakeTransport:
    channel_id: str
    sent: list[str] = dataclasses.field(default_factory=list)

    def send(self, body: str) -> tuple[object, ...]:
        self.sent.append(body)
        return ()


def _manifest(*, breaking: bool = False, changelog: str = "Capability delta.") -> ManagedManifest:
    return ManagedManifest(
        schema_version=1,
        publisher="publisher",
        skill="managed-x",
        release_sequence=7,
        source_commit=None,
        skill_sha256="a" * 64,
        previous_sha256=None,
        compatibility="any",
        breaking=breaking,
        revoked_digests=(),
        changelog=changelog,
        migration="run scripts/migrate.sh" if breaking else None,
    )


def test_announce_release_when_channel_present_then_sends_one_notification() -> None:
    # Given: a validated manifest and a fake transport bound to the announce channel.
    manifest = _manifest()
    transport = FakeTransport(channel_id="123")

    # When: the announce post is rendered.
    announce_release(manifest, "managed-x/v7", transport=transport, channel_id="123")

    # Then: one notification is sent with the required release facts.
    assert len(transport.sent) == 1
    body = transport.sent[0]
    assert "managed-x" in body
    assert "managed-x/v7" in body
    assert "aaaaaaaaaaaa" in body
    assert "breaking=false" in body
    assert "publisher-node canary 진행 중" in body


@pytest.mark.parametrize("channel_id", [None, ""])
def test_announce_release_when_channel_is_missing_then_noops(channel_id: str | None) -> None:
    # Given: no announce channel and a fake transport.
    manifest = _manifest()
    transport = FakeTransport(channel_id="123")

    # When: announcement is attempted.
    announce_release(manifest, "managed-x/v7", transport=transport, channel_id=channel_id)

    # Then: it returns normally without sending anything.
    assert transport.sent == []


def test_announce_release_when_rendered_then_omits_activation_and_reaction_prompts() -> None:
    # Given: a normal release manifest.
    manifest = _manifest()
    transport = FakeTransport(channel_id="123")

    # When: the announce body is produced.
    announce_release(manifest, "managed-x/v7", transport=transport, channel_id="123")

    # Then: it contains no activation or reaction call-to-action.
    body = transport.sent[0]
    assert "\u2705" not in body
    assert "활성화" not in body
    assert "리액션" not in body


def test_announce_release_when_changelog_contains_urls_then_redacts_repo_and_key_material() -> None:
    # Given: a changelog that would leak repository or token-shaped material if echoed verbatim.
    manifest = _manifest(
        changelog="See https://example.com/repo.git and git@github.com:org/repo.git; token sk-abc ghp_def.",
    )
    transport = FakeTransport(channel_id="123")

    # When: the announce body is rendered.
    announce_release(manifest, "managed-x/v7", transport=transport, channel_id="123")

    # Then: the message omits repository URL fragments and key-shaped strings.
    body = transport.sent[0]
    assert "http" not in body
    assert "git@" not in body
    assert ".git" not in body
    assert "sk-" not in body
    assert "ghp_" not in body


@pytest.mark.parametrize("breaking, marker_present", [(True, True), (False, False)])
def test_announce_release_when_breaking_changes_then_marks_only_breaking_releases(
    breaking: bool, marker_present: bool
) -> None:
    # Given: a breaking or non-breaking manifest.
    manifest = _manifest(breaking=breaking)
    transport = FakeTransport(channel_id="123")

    # When: the message is rendered.
    announce_release(manifest, "managed-x/v7", transport=transport, channel_id="123")

    # Then: only breaking releases carry a visible breaking marker.
    body = transport.sent[0]
    assert ("⚠ BREAKING" in body) is marker_present
