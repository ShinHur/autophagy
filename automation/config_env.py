"""Fail-closed accessors for public deployment configuration."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Final, Literal, assert_never as _assert_never

_SNOWFLAKE_PATTERN: Final = re.compile(r"^[0-9]{17,20}$")
_HOST_LABEL_PATTERN: Final = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_EMAIL_PATTERN: Final = re.compile(
    r"^[^@\s]+@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


class ConfigError(RuntimeError):
    """Raised when required public configuration is absent or malformed."""


def require_env(
    name: str,
    *,
    validator: Callable[[str], bool] | None = None,
    hint: str = "",
) -> str:
    """Return one non-blank environment value or fail with remediation guidance."""
    value = os.environ.get(name)
    remediation = hint.strip() or f"Set {name} for this deployment"
    if value is None or not value.strip():
        raise ConfigError(
            f"{name}: required value is missing; {remediation}. "
            "Copy .env.example to a private environment file and set the value."
        )
    if validator is not None and not validator(value):
        raise ConfigError(
            f"{name}: configured value is malformed; {remediation}. "
            "Use .env.example as the deployment key reference."
        )
    return value


def optional_env(name: str) -> str | None:
    """Return a non-blank optional environment value, otherwise ``None``."""
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value


def is_snowflake(value: str) -> bool:
    return _SNOWFLAKE_PATTERN.fullmatch(value) is not None


def is_hostname(value: str) -> bool:
    if not value or len(value) > 253:
        return False
    return all(_HOST_LABEL_PATTERN.fullmatch(label) is not None for label in value.split("."))


def is_email(value: str) -> bool:
    return len(value) <= 254 and _EMAIL_PATTERN.fullmatch(value) is not None


def _snowflake_env(name: str) -> str:
    return require_env(
        name,
        validator=is_snowflake,
        hint="Set the numeric Discord ID copied with Discord Developer Mode",
    )


def _absolute_path_env(name: str) -> Path:
    value = require_env(
        name,
        validator=lambda candidate: Path(candidate).is_absolute(),
        hint="Set an absolute path for this deployment",
    )
    return Path(value)


def discord_owner_id() -> str:
    return _snowflake_env("DISCORD_OWNER_ID")


def discord_guild_id() -> str:
    return _snowflake_env("DISCORD_GUILD_ID")


def discord_owner_dm_channel_id() -> str:
    return _snowflake_env("DISCORD_OWNER_DM_CHANNEL_ID")


def discord_approvals_channel_id() -> str:
    return _snowflake_env("DISCORD_APPROVALS_CHANNEL_ID")


def discord_bot_user_id(role: Literal["agent", "peer"]) -> str:
    match role:
        case "agent":
            name = "DISCORD_BOT_USER_ID_AGENT"
        case "peer":
            name = "DISCORD_BOT_USER_ID_PEER"
        case unreachable:
            _assert_never(unreachable)
    return _snowflake_env(name)


def deploy_ssh_host() -> str:
    return require_env(
        "DEPLOY_SSH_HOST",
        validator=is_hostname,
        hint="Set the SSH hostname from your deployment inventory",
    )


def deploy_root() -> Path:
    return _absolute_path_env("AUTOPHAGY_DEPLOY_ROOT")


def private_root() -> Path:
    return _absolute_path_env("AUTOPHAGY_PRIVATE_ROOT")


def skills_live_root() -> Path:
    return _absolute_path_env("AUTOPHAGY_SKILLS_ROOT")


def hermes_root() -> Path:
    return Path.home() / ".hermes"


def owner_email() -> str:
    return require_env(
        "OWNER_EMAIL",
        validator=is_email,
        hint="Set the owner's delivery address",
    )


def organization_label() -> str:
    return require_env(
        "ORGANIZATION_LABEL",
        hint="Set the public display label for the deployment organization",
    )


def gcp_project_id() -> str:
    return require_env(
        "GCP_PROJECT_ID",
        hint="Set the project ID shown in the Google Cloud console",
    )


def budget_sheet_id() -> str:
    return require_env(
        "BUDGET_SHEET_ID",
        hint="Set the spreadsheet ID from the budget sheet URL",
    )


def site_mail_backend_config() -> Path:
    return _absolute_path_env("SITE_MAIL_BACKEND_CONFIG")
