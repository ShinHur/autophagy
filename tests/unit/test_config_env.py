"""Tests for the public environment configuration contract."""

from __future__ import annotations

import inspect
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from automation import config_env
from tests.unit._synthetic import (
    APPROVALS_CHANNEL_ID,
    BOT_USER_ID_AGENT,
    BOT_USER_ID_PEER,
    GUILD_ID,
    OWNER_DM_CHANNEL_ID,
    OWNER_EMAIL,
    OWNER_ID,
    fake_snowflake,
    synthetic_env,
)

type ConfigValue = str | Path


@dataclass(frozen=True, slots=True)
class AccessorCase:
    name: str
    env_name: str
    value: str
    expected: ConfigValue
    call: Callable[[], ConfigValue]


ACCESSOR_CASES: Final = (
    AccessorCase(
        "discord_owner_id",
        "DISCORD_OWNER_ID",
        OWNER_ID,
        OWNER_ID,
        config_env.discord_owner_id,
    ),
    AccessorCase(
        "discord_guild_id",
        "DISCORD_GUILD_ID",
        GUILD_ID,
        GUILD_ID,
        config_env.discord_guild_id,
    ),
    AccessorCase(
        "discord_owner_dm_channel_id",
        "DISCORD_OWNER_DM_CHANNEL_ID",
        OWNER_DM_CHANNEL_ID,
        OWNER_DM_CHANNEL_ID,
        config_env.discord_owner_dm_channel_id,
    ),
    AccessorCase(
        "discord_approvals_channel_id",
        "DISCORD_APPROVALS_CHANNEL_ID",
        APPROVALS_CHANNEL_ID,
        APPROVALS_CHANNEL_ID,
        config_env.discord_approvals_channel_id,
    ),
    AccessorCase(
        "discord_bot_user_id_agent",
        "DISCORD_BOT_USER_ID_AGENT",
        BOT_USER_ID_AGENT,
        BOT_USER_ID_AGENT,
        lambda: config_env.discord_bot_user_id("agent"),
    ),
    AccessorCase(
        "discord_bot_user_id_peer",
        "DISCORD_BOT_USER_ID_PEER",
        BOT_USER_ID_PEER,
        BOT_USER_ID_PEER,
        lambda: config_env.discord_bot_user_id("peer"),
    ),
    AccessorCase(
        "deploy_ssh_host",
        "DEPLOY_SSH_HOST",
        "node-a",
        "node-a",
        config_env.deploy_ssh_host,
    ),
    AccessorCase(
        "deploy_root",
        "AUTOPHAGY_DEPLOY_ROOT",
        "/opt/example-deploy",
        Path("/opt/example-deploy"),
        config_env.deploy_root,
    ),
    AccessorCase(
        "private_root",
        "AUTOPHAGY_PRIVATE_ROOT",
        "/var/lib/example-private",
        Path("/var/lib/example-private"),
        config_env.private_root,
    ),
    AccessorCase(
        "skills_live_root",
        "AUTOPHAGY_SKILLS_ROOT",
        "/opt/example-skills/live",
        Path("/opt/example-skills/live"),
        config_env.skills_live_root,
    ),
    AccessorCase(
        "owner_email",
        "OWNER_EMAIL",
        OWNER_EMAIL,
        OWNER_EMAIL,
        config_env.owner_email,
    ),
    AccessorCase(
        "organization_label",
        "ORGANIZATION_LABEL",
        "Example Organization",
        "Example Organization",
        config_env.organization_label,
    ),
    AccessorCase(
        "gcp_project_id",
        "GCP_PROJECT_ID",
        "example-project",
        "example-project",
        config_env.gcp_project_id,
    ),
    AccessorCase(
        "budget_sheet_id",
        "BUDGET_SHEET_ID",
        "example-budget-sheet",
        "example-budget-sheet",
        config_env.budget_sheet_id,
    ),
    AccessorCase(
        "site_mail_backend_config",
        "SITE_MAIL_BACKEND_CONFIG",
        "/etc/example/site-mail.json",
        Path("/etc/example/site-mail.json"),
        config_env.site_mail_backend_config,
    ),
)


@pytest.mark.parametrize("case", ACCESSOR_CASES, ids=lambda case: case.name)
@pytest.mark.parametrize("missing_value", [None, "", " \t"], ids=["unset", "empty", "blank"])
def test_accessor_fails_closed_when_value_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    case: AccessorCase,
    missing_value: str | None,
) -> None:
    # Given
    if missing_value is None:
        monkeypatch.delenv(case.env_name, raising=False)
    else:
        monkeypatch.setenv(case.env_name, missing_value)

    # When
    with pytest.raises(config_env.ConfigError) as captured:
        case.call()

    # Then
    message = str(captured.value)
    assert case.env_name in message
    assert ".env.example" in message


@pytest.mark.parametrize("case", ACCESSOR_CASES, ids=lambda case: case.name)
def test_accessor_returns_configured_value(
    monkeypatch: pytest.MonkeyPatch,
    case: AccessorCase,
) -> None:
    # Given
    monkeypatch.setenv(case.env_name, case.value)

    # When
    result = case.call()

    # Then
    assert result == case.expected


@pytest.mark.parametrize(
    ("validator", "malformed"),
    [
        (config_env.is_snowflake, "abc"),
        (config_env.is_hostname, "bad host"),
        (config_env.is_email, "nope"),
    ],
)
def test_validator_rejects_malformed_value(
    validator: Callable[[str], bool],
    malformed: str,
) -> None:
    # Given / When / Then
    assert not validator(malformed)


@pytest.mark.parametrize(
    "case",
    [case for case in ACCESSOR_CASES if isinstance(case.expected, Path)],
    ids=lambda case: case.name,
)
def test_path_accessor_rejects_relative_path(
    monkeypatch: pytest.MonkeyPatch,
    case: AccessorCase,
) -> None:
    # Given
    monkeypatch.setenv(case.env_name, "relative/path")

    # When / Then
    with pytest.raises(config_env.ConfigError):
        case.call()


def test_owner_email_rejects_malformed_address(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    monkeypatch.setenv("OWNER_EMAIL", "nope")

    # When / Then
    with pytest.raises(config_env.ConfigError):
        config_env.owner_email()


def test_deploy_host_rejects_malformed_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    monkeypatch.setenv("DEPLOY_SSH_HOST", "bad host")

    # When / Then
    with pytest.raises(config_env.ConfigError):
        config_env.deploy_ssh_host()


def test_require_env_rejects_value_when_validator_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.setenv("TEST_VALUE", "invalid")

    # When / Then
    with pytest.raises(config_env.ConfigError, match=r"TEST_VALUE.*\.env\.example"):
        config_env.require_env("TEST_VALUE", validator=lambda value: value == "valid")


def test_optional_env_returns_none_for_missing_or_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    monkeypatch.delenv("OPTIONAL_VALUE", raising=False)

    # When / Then
    assert config_env.optional_env("OPTIONAL_VALUE") is None
    monkeypatch.setenv("OPTIONAL_VALUE", "  ")
    assert config_env.optional_env("OPTIONAL_VALUE") is None


def test_hermes_root_is_derived_and_ignores_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given
    monkeypatch.setenv("HERMES_ROOT", "/tmp/not-hermes")

    # When
    result = config_env.hermes_root()

    # Then
    assert result == Path.home() / ".hermes"


def test_fake_snowflake_satisfies_validator() -> None:
    # Given / When
    value = fake_snowflake(99)

    # Then
    assert config_env.is_snowflake(value)


def test_synthetic_env_satisfies_every_public_accessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given
    for name in tuple(os.environ):
        monkeypatch.delenv(name)
    for name, value in synthetic_env().items():
        monkeypatch.setenv(name, value)
    helpers = {
        "hermes_root",
        "is_email",
        "is_hostname",
        "is_snowflake",
        "optional_env",
        "require_env",
    }
    accessors = {
        name: function
        for name, function in inspect.getmembers(config_env, inspect.isfunction)
        if not name.startswith("_") and name not in helpers
    }

    # When / Then
    for name, accessor in accessors.items():
        if name == "discord_bot_user_id":
            assert accessor("agent") == BOT_USER_ID_AGENT
            assert accessor("peer") == BOT_USER_ID_PEER
            continue
        assert not inspect.signature(accessor).parameters, f"unsupported accessor signature: {name}"
        accessor()
