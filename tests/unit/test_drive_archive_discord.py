"""Deleted approval message must read as gone, not as an error."""

from __future__ import annotations

from urllib.error import HTTPError

import pytest

from automation.drive_archive import discord


def test_content_returns_empty_on_deleted_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def _api(*args: object, **kwargs: object) -> None:
        raise HTTPError(url="https://x", code=404, msg="Not Found", hdrs=None, fp=None)

    monkeypatch.setattr(discord, "_api", _api)

    transport = discord.DiscordApprovals(token="t", channel_id="c")

    assert transport.content("m1") == ""


def test_content_reraises_non_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def _api(*args: object, **kwargs: object) -> None:
        raise HTTPError(url="https://x", code=500, msg="Not Found", hdrs=None, fp=None)

    monkeypatch.setattr(discord, "_api", _api)

    transport = discord.DiscordApprovals(token="t", channel_id="c")

    with pytest.raises(HTTPError):
        transport.content("m1")
