"""Every drive-archive approval action targets the channel the RECORD names (AS-1.8).

The watcher used to build its ``ApprovalRequest`` with ``channel_id="approvals"``
— a label, not a snowflake — so a reaction poll could only ever hit whichever
channel the transport happened to be bound to. These tests lock the replacement:
the digest's channel is resolved ONCE through the shared directory, persisted on
the pending batch, and replayed by every later read. A batch written before this
schema carries no binding and still drains through ``legacy_binding``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from automation.drive_archive import approval_binding, discord, paths, sync_cli
from automation.drive_archive import confirm_reaction_watch as watch
from automation.drive_archive.config import CANCEL_EMOJI
from automation.drive_archive.manifest import FileEntry
from automation.drive_archive.pending import PendingBatch, PendingBatchStore
from automation.interop.approval_lease import FileKeyLease
from automation.interop import approval_surface
from automation.interop.approval_surface import (
    ApprovalKind,
    ApprovalSurface,
    ApprovalSurfaceError,
    ChannelFacts,
    required_surface,
)
from tests.unit._synthetic import APPROVALS_CHANNEL_ID, OWNER_DM_CHANNEL_ID, OWNER_ID, fake_snowflake

OWNER = OWNER_ID
# What the resolver answers today: the guild #approvals channel.
GUILD_APPROVALS = APPROVALS_CHANNEL_ID
# What ONE stored batch says its digest actually lives in — deliberately NOT what
# the resolver answers, so replaying the record is distinguishable from resolving.
STORED_CHANNEL = fake_snowflake(9)
OWNER_DM = OWNER_DM_CHANNEL_ID
TARGET = "tool:drive_archive_batch_upload:drive_archive.batch_upload"
HASH = "sha256:" + "a" * 64


class RecordingApi:
    """Stands in for ``discord._api`` and records every ``(method, path)`` asked for."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.posted = 0

    def __call__(
        self,
        method: str,
        path: str,
        token: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        del token, payload
        self.calls.append((method, path))
        if method == "POST" and path == "/users/@me/channels":
            return {"id": OWNER_DM}
        if method == "POST" and path.endswith("/messages"):
            self.posted += 1
            return {"id": f"msg{self.posted}"}
        if method == "GET" and path == f"/channels/{GUILD_APPROVALS}":
            return {"id": GUILD_APPROVALS, "type": 0, "name": "approvals"}
        if method == "GET" and path == f"/channels/{OWNER_DM}":
            return {"id": OWNER_DM, "type": 1, "recipients": [{"id": OWNER}]}
        if method == "GET" and "/reactions/" in path:
            return [{"id": OWNER, "bot": False}] if CANCEL_EMOJI in path else []
        if method == "GET" and "/messages/" in path:
            return {"content": f"digest {HASH}"}
        return None

    @property
    def channels(self) -> list[str]:
        """The channel id each ``/channels/<id>/...`` call targeted, in order."""
        return [
            path.removeprefix("/channels/").split("/")[0]
            for _, path in self.calls
            if path.startswith("/channels/")
        ]


class FixedDirectory:
    """A ``ChannelDirectory`` that answers without Discord (SI-3 facts included)."""

    def owner_dm(self) -> str:
        return OWNER_DM

    def skill_approvals(self) -> str:
        return GUILD_APPROVALS

    def describe(self, channel_id: str) -> ChannelFacts:
        if channel_id == OWNER_DM:
            return ChannelFacts(1, "", (OWNER,))
        return ChannelFacts(0, "approvals", ())


class RecordingCommand:
    def __init__(self) -> None:
        self.ran: list[str] = []

    def run(self, pending: PendingBatch) -> bool:
        self.ran.append(pending.action_hash)
        return True


@pytest.fixture
def flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RecordingApi:
    """A drive-archive runtime with state outside the checkout and no network."""
    repo = tmp_path / "repo"
    (repo / ".omo" / "plans").mkdir(parents=True)
    (repo / ".omo" / "plans" / "a.md").write_text("plan A", encoding="utf-8")
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "features.md").write_text("feat", encoding="utf-8")
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"owner_id": OWNER, "personal_approvals_channel_id": GUILD_APPROVALS}),
        encoding="utf-8",
    )
    denylist = Path(__file__).resolve().parents[2] / "configs" / "external-effect-tools.yaml"
    monkeypatch.setenv("AUTOPHAGY_REPO_ROOT", str(repo))
    monkeypatch.setenv("DRIVE_ARCHIVE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("DRIVE_ARCHIVE_APPROVAL_LOG", str(tmp_path / "state" / "approvals.jsonl"))
    monkeypatch.setenv("DRIVE_ARCHIVE_DENYLIST", str(denylist))
    monkeypatch.setenv("INTEROP_CONFIG", str(config_file))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "unit-test-credential")
    monkeypatch.delenv("DRIVE_ARCHIVE_DISCORD_STUB", raising=False)
    api = RecordingApi()
    monkeypatch.setattr(discord, "_api", api)
    return api


def _legacy_json() -> dict[str, object]:
    """A pending batch exactly as it was serialised before this schema."""
    return {
        "action_hash": HASH,
        "target_id": TARGET,
        "message_id": "msg-legacy",
        "project": "autophagy",
        "created_at": "2026-07-24T00:00:00Z",
        "files": [{"path": "docs/features.md", "sha256": "b" * 64}],
    }


def test_pending_batch_persists_its_binding(flow: RecordingApi) -> None:
    # Given: a changed in-scope deliverable and a resolver that answers both the
    # owner DM and the guild #approvals channel.
    # When: the producer posts one digest.
    assert sync_cli.main(["request"]) == 0

    # Then: the record carries the whole binding it was posted under — kind,
    # surface, a digit-only snowflake, and the policy version it was stamped at.
    records = PendingBatchStore(paths.pending_dir()).all_strict()
    assert len(records) == 1
    record = records[0]
    assert record.kind == ApprovalKind.DRIVE_ARCHIVE.value
    assert record.surface == ApprovalSurface.OWNER_DM.value
    assert record.channel_id == OWNER_DM
    assert record.channel_id.isdigit()
    assert record.policy_version > 0
    assert record.is_bound is True


def test_watcher_uses_the_stored_channel(flow: RecordingApi, tmp_path: Path) -> None:
    # Given: a batch whose digest lives in a channel the resolver does NOT answer,
    # and a transport bound to the resolver's channel (what a tick builds today).
    store = PendingBatchStore(paths.pending_dir())
    store.put(
        PendingBatch(
            HASH,
            TARGET,
            "msg-bound",
            "autophagy",
            "2026-07-24T00:00:00Z",
            (FileEntry("docs/features.md", "b" * 64),),
            kind=ApprovalKind.DRIVE_ARCHIVE.value,
            surface=ApprovalSurface.SKILL_APPROVALS.value,
            channel_id=STORED_CHANNEL,
            policy_version=1,
        )
    )
    watcher = watch.DriveArchiveWatcher(
        store=store,
        transport=discord.DiscordApprovals(token="unit-test-credential", channel_id=GUILD_APPROVALS),
        commands=RecordingCommand(),
        owner_id=OWNER,
        approval_log=tmp_path / "approvals.jsonl",
        now=lambda: datetime(2026, 7, 24, 0, 0, 30, tzinfo=UTC),
        lease=FileKeyLease(tmp_path / "leases"),
    )

    # When: the owner's ⛔ is polled and the digest is superseded.
    watcher.run_once()

    # Then: every read and the delete hit the channel the RECORD names, never the
    # channel the tick resolved — and no call ever addresses the literal label.
    digest_calls = [channel for channel in flow.channels if channel != OWNER_DM]
    assert digest_calls, flow.calls
    assert set(digest_calls) == {STORED_CHANNEL}
    assert GUILD_APPROVALS not in flow.channels
    assert "approvals" not in flow.channels
    source = (
        Path(__file__).resolve().parents[2]
        / "automation/drive_archive/confirm_reaction_watch.py"
    ).read_text(encoding="utf-8")
    assert '"approvals"' not in source
    assert "'approvals'" not in source


def test_legacy_batch_without_a_binding_still_resolves(flow: RecordingApi, tmp_path: Path) -> None:
    # Given: one pre-schema record next to one fully bound record.
    store = PendingBatchStore(paths.pending_dir())
    paths.pending_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    (paths.pending_dir() / "legacy.json").write_text(
        json.dumps(_legacy_json()), encoding="utf-8"
    )
    store.put(
        PendingBatch(
            "sha256:" + "c" * 64,
            TARGET,
            "msg-bound",
            "autophagy",
            "2026-07-24T00:00:00Z",
            (FileEntry("docs/features.md", "b" * 64),),
            kind=ApprovalKind.DRIVE_ARCHIVE.value,
            surface=ApprovalSurface.SKILL_APPROVALS.value,
            channel_id=GUILD_APPROVALS,
            policy_version=1,
        )
    )

    # When: the store is read strictly — one old row must not poison the tick.
    records = store.all_strict()

    # Then: both rows load, the old one is simply unbound (policy version 0)…
    assert len(records) == 2
    legacy = next(record for record in records if record.message_id == "msg-legacy")
    assert legacy.is_bound is False
    assert legacy.channel_id == ""
    assert legacy.policy_version == 0

    # …and it still resolves, through the legacy migrator, to the concrete channel
    # its digest was posted on, so the historical approval stays consumable.
    binding = approval_binding.stored_binding(legacy, FixedDirectory())
    assert binding.channel_id == GUILD_APPROVALS
    assert binding.surface is ApprovalSurface.SKILL_APPROVALS
    assert binding.policy_version == 0

    # And a record claiming another flow's kind is refused, never retargeted.
    with pytest.raises(ApprovalSurfaceError):
        approval_binding.stored_binding(
            PendingBatch(
                HASH,
                TARGET,
                "msg-alien",
                "autophagy",
                "2026-07-24T00:00:00Z",
                (),
                kind=ApprovalKind.REPAIR.value,
                surface=ApprovalSurface.SKILL_APPROVALS.value,
                channel_id=GUILD_APPROVALS,
                policy_version=1,
            ),
            FixedDirectory(),
        )


def test_digest_posts_to_the_owner_dm(flow: RecordingApi) -> None:
    # Given: a runtime whose config still carries the guild #approvals id, so the
    # resolver can answer BOTH surfaces and the choice below is policy, not
    # availability.
    # When: the producer posts one batch digest.
    assert sync_cli.main(["request"]) == 0

    # Then: the single approval message lands in the DM this bot opened with the
    # owner, and the guild channel is never addressed at all.
    posts = [path for method, path in flow.calls if method == "POST" and path.endswith("/messages")]
    assert posts == [f"/channels/{OWNER_DM}/messages"]
    assert GUILD_APPROVALS not in flow.channels

    # …the record names that surface at the version it was stamped under…
    record = PendingBatchStore(paths.pending_dir()).all_strict()[0]
    assert (record.surface, record.channel_id) == (ApprovalSurface.OWNER_DM.value, OWNER_DM)
    assert record.policy_version == approval_surface.POLICY_VERSION

    # …and every version allocated before this flip keeps the surface it always
    # had, so no already-stored batch can be reinterpreted (append-only ledger).
    assert all(
        approval_surface.surface_at_policy(ApprovalKind.DRIVE_ARCHIVE, version)
        is ApprovalSurface.SKILL_APPROVALS
        for version in range(approval_surface.POLICY_VERSION)
    )


def test_a_batch_bound_before_the_flip_still_drains_from_its_own_channel(
    flow: RecordingApi,
) -> None:
    # Given: a digest posted before the flip — stamped SKILL_APPROVALS at v1.
    posted_before_the_flip = PendingBatch(
        HASH,
        TARGET,
        "msg-pre-flip",
        "autophagy",
        "2026-07-24T00:00:00Z",
        (FileEntry("docs/features.md", "b" * 64),),
        kind=ApprovalKind.DRIVE_ARCHIVE.value,
        surface=ApprovalSurface.SKILL_APPROVALS.value,
        channel_id=GUILD_APPROVALS,
        policy_version=1,
    )

    # When: a later tick replays that stored binding under the current policy.
    binding = approval_binding.stored_binding(posted_before_the_flip, FixedDirectory())

    # Then: it still points at the channel the owner's message actually lives in —
    # a stored record is authoritative and is never retargeted (SI-1) — even though
    # a brand-new digest would now be posted to the DM instead.
    assert (binding.surface, binding.channel_id) == (
        ApprovalSurface.SKILL_APPROVALS,
        GUILD_APPROVALS,
    )
    assert required_surface(ApprovalKind.DRIVE_ARCHIVE) is ApprovalSurface.OWNER_DM
