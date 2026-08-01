"""Node-runtime side effects for the memory-curator cron watcher.

``alert_owner`` is the near-cap notification (best-effort owner notification) — NOT an
approval, so it stays here.  The security-critical ``promote`` effect posts a
twin draft for owner confirmation through the wiki gate's sanctioned
``create_draft`` + ``post_confirm_message`` path; it never re-implements the
``approval_lifecycle`` boundary.

Both effects are exercised on the node (live Discord / wiki gate) and are
deploy-validated, like every watcher here.  ``alert_owner`` fails closed: a
missing token/config or an HTTP error is swallowed so a bad tick never
crashes the cron.
"""

from __future__ import annotations

import importlib
import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .binding import PromotionReceipt
from .promotion import PromotionProposal

_INTEROP_CONFIG = Path(
    os.environ.get("INTEROP_CONFIG", str(Path.home() / ".hermes/interop/config.json"))
)

#: Injected Discord POST — ``(token, path, payload) -> response dict``.
DiscordPost = Callable[[str, str, "dict[str, str]"], "dict[str, Any]"]


def _discord_post(token: str, path: str, payload: dict[str, str]) -> dict[str, Any]:
    from urllib.request import Request, urlopen

    request = Request(
        f"https://discord.com/api/v10{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://github.com/orientpine/autophagy-agents, 0)",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310
        body = response.read().decode("utf-8")
    parsed: dict[str, Any] = json.loads(body) if body else {}
    return parsed


def _owner_id() -> str:
    config = json.loads(_INTEROP_CONFIG.read_text(encoding="utf-8"))
    owner = config.get("owner_id") if isinstance(config, dict) else None
    if not isinstance(owner, str) or not owner:
        raise ValueError("interop config missing owner_id")
    return owner


def alert_owner(message: str, *, post: DiscordPost | None = None) -> bool:
    """Best-effort near-cap owner notice; swallow every failure (never crash the tick)."""
    if os.environ.get("MEMORY_CURATOR_DRY_RUN") == "1":
        print(f"DRY-RUN alert: {message}")
        return False
    sender = post or _discord_post
    try:
        token = os.environ.get("DISCORD_BOT_TOKEN", "")
        if not token:
            return False
        channel = sender(token, "/users/@me/channels", {"recipient_id": _owner_id()})
        channel_id = str(channel["id"])
        _ = sender(token, f"/channels/{channel_id}/messages", {"content": message})
        return True
    except Exception:  # noqa: BLE001 — best-effort notification, must not crash the cron
        return False



# --- promotion: thin reuse of the wiki gate's sanctioned approval flow ------ #
WikiPromoteRunner = Callable[[PromotionProposal], "PromotionReceipt | None"]


def _twin_meta_and_body(proposal: PromotionProposal, now: str) -> tuple[dict[str, object], str]:
    """Pure: the wiki frontmatter (SI-3 observed/advisory) + body for a promotion."""
    meta: dict[str, object] = {
        "title": proposal.title,
        "tags": ["twin", proposal.twin_kind],
        "created": now,
        "updated": now,
        "links": [],
        "kind": proposal.twin_kind,
        "authority": proposal.authority,  # advisory — proposer cap
        "provenance": proposal.provenance,  # observed — proposer cap
    }
    return meta, proposal.body


def _wiki_gate_promote(proposal: PromotionProposal) -> PromotionReceipt | None:
    """Node-runtime: post the twin draft through the wiki gate's OWN sanctioned
    ``create_draft`` + ``post_confirm_message`` (owner-DM ✅ via approval_lifecycle).

    This reuses the wiki skill's approval boundary verbatim: it NEVER resolves a
    surface, writes confirm_message_id, or touches approval_lifecycle — the gate
    does all of that.  ``post_confirm_message`` persists the full owner-DM binding
    (via ``WikiApprovalGate.commit``) and its one-live-confirm-per-key invariant
    makes a repeated tick a no-op.  The deployed wiki scripts dir must be on
    ``sys.path`` (the cron wrapper adds it) with the wiki runtime env set.
    """
    if os.environ.get("MEMORY_CURATOR_DRY_RUN") == "1":
        return None

    wiki_gate = importlib.import_module("wiki_gate")
    wiki_store = importlib.import_module("wiki_store")

    meta = _twin_meta_and_body(proposal, wiki_store.utc_now())[0]
    note_text = wiki_store.compose_note(meta, proposal.body)
    draft = wiki_gate.create_draft("create", proposal.slug, note_text, "dm")
    result = wiki_gate.post_confirm_message(draft)
    confirm_message_id = result.get("confirm_message_id")
    if not isinstance(confirm_message_id, str):
        return None
    return PromotionReceipt(
        draft_id=draft["id"],
        confirm_message_id=confirm_message_id,
        slug=proposal.slug,
        note_sha256=draft["sha256"],
    )


def post_promotion(
    proposal: PromotionProposal, *, runner: WikiPromoteRunner | None = None
) -> PromotionReceipt | None:
    """Propose one durable entry to the twin for owner-DM ✅.

    Returns the approval receipt when the confirm was posted.  Any failure
    returns None — retried next tick, and the wiki gate's one-live-confirm-per-key
    invariant prevents a double post.
    """
    run = runner or _wiki_gate_promote
    try:
        return run(proposal)
    except Exception:  # noqa: BLE001 — a failed post is retried next tick, never crashes
        return None


def read_twin(slug: str, *, wiki_root: Path | None = None) -> bytes | None:
    """Read one regular twin note without following a final-component symlink."""
    root = (
        wiki_root
        if wiki_root is not None
        else Path(os.environ.get("WIKI_ROOT", "~/wiki")).expanduser()
    )
    path = root / f"{slug}.md"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    except OSError:
        return None
    finally:
        os.close(descriptor)
