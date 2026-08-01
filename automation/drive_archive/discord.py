"""Discord approval transport for drive-archive, plus an offline stub.

REST transport mirrors ``budget_confirm``; ``StubApprovals`` records posts/reads
reactions on disk so the CLI and e2e run fully offline (``DRIVE_ARCHIVE_DISCORD_STUB``).
Both types satisfy ``confirm.ApprovalPollTransport`` (content + reaction_users).
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from automation.drive_archive import approval_binding
from automation.interop.approval_surface import ApprovalSurfaceError

API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/orientpine/autophagy-agents, 0)"
ENV_SECRETS = Path.home() / ".env.secrets"


class DiscordError(RuntimeError):
    """The approval channel could not be resolved or the API rejected a call."""


def bot_token() -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if token:
        return token
    try:
        lines = ENV_SECRETS.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        if line.startswith("DISCORD_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise DiscordError("DISCORD_BOT_TOKEN 없음 — Drive 아카이브 승인 경로 사용 불가")


def _api(method: str, path: str, token: str, payload: dict[str, Any] | None = None) -> Any:
    request = Request(
        f"{API}{path}",
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method=method,
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310
        body = response.read().decode("utf-8")
    return json.loads(body) if body else None


def _resolved(resolve: Callable[[], str]) -> str:
    """A directory failure is this transport's own refusal — never a fallback."""
    try:
        return resolve()
    except ApprovalSurfaceError as error:
        raise DiscordError(f"승인 표면 해석 실패 — Drive 아카이브 요청 거부: {error}") from error


@dataclass(frozen=True, slots=True)
class DiscordApprovals:
    token: str
    channel_id: str

    def post(self, content: str) -> str:
        message = _api("POST", f"/channels/{self.channel_id}/messages", self.token, {"content": content})
        return str(message["id"])

    def add_reaction(self, message_id: str, emoji: str) -> None:
        _api(
            "PUT",
            f"/channels/{self.channel_id}/messages/{message_id}/reactions/{quote(emoji, safe='')}/@me",
            self.token,
        )

    def delete(self, message_id: str) -> None:
        _api("DELETE", f"/channels/{self.channel_id}/messages/{message_id}", self.token)

    def content(self, message_id: str) -> str:
        try:
            message = _api("GET", f"/channels/{self.channel_id}/messages/{message_id}", self.token)
        except HTTPError as error:
            if error.code == 404:
                return ""  # 삭제된 메시지 = 승인 표면 소멸 (reaction_users와 대칭) — 오류 아님
            raise
        return str(message.get("content", "")) if isinstance(message, dict) else ""

    def reaction_users(self, message_id: str, emoji: str) -> tuple[tuple[str, bool], ...]:
        try:
            users = _api(
                "GET",
                f"/channels/{self.channel_id}/messages/{message_id}"
                f"/reactions/{quote(emoji, safe='')}?limit=100",
                self.token,
            )
        except HTTPError as error:
            if error.code == 404:
                return ()
            raise
        if not isinstance(users, list):
            raise DiscordError("승인 리액션 응답이 유효하지 않음 — 거부")
        return tuple(
            (str(user.get("id", "")), bool(user.get("bot", False)))
            for user in users
            if isinstance(user, dict)
        )

    def dm(self, owner: str, content: str) -> str:
        """Result notices only — the shared directory opens the DM, never this module.

        A notice resolves its own DM instead of reusing ``channel_id``: the two
        happen to be the same channel while approvals route to a DM, but
        an upload receipt is not an approval and must not follow the approval
        surface wherever policy moves it next.
        """
        channel_id = _resolved(
            lambda: approval_binding.approval_directory(self.token, _api, owner).owner_dm()
        )
        message = _api("POST", f"/channels/{channel_id}/messages", self.token, {"content": content})
        return str(message["id"])


@dataclass(frozen=True, slots=True)
class StubApprovals:
    root: Path

    def post(self, content: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        message_id = "stub" + secrets.token_hex(4)
        (self.root / f"{message_id}.json").write_text(
            json.dumps({"id": message_id, "content": content}, ensure_ascii=False), encoding="utf-8"
        )
        return message_id

    def add_reaction(self, message_id: str, emoji: str) -> None:
        return None

    def delete(self, message_id: str) -> None:
        (self.root / f"{message_id}.json").unlink(missing_ok=True)

    def content(self, message_id: str) -> str:
        try:
            data = json.loads((self.root / f"{message_id}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ""
        return str(data.get("content", ""))

    def reaction_users(self, message_id: str, emoji: str) -> tuple[tuple[str, bool], ...]:
        try:
            data = json.loads((self.root / f"{message_id}.reactions.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ()
        entries = data.get(emoji, []) if isinstance(data, dict) else []
        return tuple((str(item[0]), bool(item[1])) for item in entries)

    def dm(self, owner: str, content: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        message_id = "dm" + secrets.token_hex(4)
        (self.root / f"{message_id}.dm.json").write_text(
            json.dumps({"owner": owner, "content": content}, ensure_ascii=False), encoding="utf-8"
        )
        return message_id


def configured_approvals() -> DiscordApprovals | StubApprovals:
    stub = os.environ.get("DRIVE_ARCHIVE_DISCORD_STUB", "")
    if stub:
        return StubApprovals(Path(stub))
    token = bot_token()
    channel_id = _resolved(lambda: approval_binding.new_binding(token, _api).channel_id)
    return DiscordApprovals(token=token, channel_id=channel_id)
