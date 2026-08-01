from __future__ import annotations

from typing import Final


def fake_snowflake(n: int) -> str:
    return str(10**17 + n)


OWNER_ID: Final = fake_snowflake(1)
GUILD_ID: Final = fake_snowflake(2)
OWNER_DM_CHANNEL_ID: Final = fake_snowflake(3)
APPROVALS_CHANNEL_ID: Final = fake_snowflake(4)
BOT_USER_ID_AGENT: Final = fake_snowflake(5)
BOT_USER_ID_PEER: Final = fake_snowflake(6)

OWNER: Final = "owner"
PERSON_A: Final = "person-alpha"
PERSON_B: Final = "person-beta"
PERSON_KO_A: Final = "가상사용자-가"
PERSON_KO_B: Final = "가상사용자-나"
OWNER_EMAIL: Final = "owner@example.invalid"
PEER_EMAIL: Final = "peer@example.invalid"
ORG_LABEL: Final = "Example Organization"
NODE_A: Final = "node-a"
NODE_B: Final = "node-b"
IP_A: Final = "192.0.2.10"
IP_B: Final = "192.0.2.11"


def synthetic_env(**overrides: str) -> dict[str, str]:
    environment = {
        "DISCORD_OWNER_ID": OWNER_ID,
        "DISCORD_GUILD_ID": GUILD_ID,
        "DISCORD_OWNER_DM_CHANNEL_ID": OWNER_DM_CHANNEL_ID,
        "DISCORD_APPROVALS_CHANNEL_ID": APPROVALS_CHANNEL_ID,
        "DISCORD_BOT_USER_ID_AGENT": BOT_USER_ID_AGENT,
        "DISCORD_BOT_USER_ID_PEER": BOT_USER_ID_PEER,
        "DEPLOY_SSH_HOST": NODE_A,
        "AUTOPHAGY_DEPLOY_ROOT": "/opt/example-deploy",
        "AUTOPHAGY_PRIVATE_ROOT": "/var/lib/example-private",
        "AUTOPHAGY_SKILLS_ROOT": "/opt/example-skills/live",
        "OWNER_EMAIL": OWNER_EMAIL,
        "ORGANIZATION_LABEL": ORG_LABEL,
        "GCP_PROJECT_ID": "example-project",
        "BUDGET_SHEET_ID": "example-budget-sheet",
        "SITE_MAIL_BACKEND_CONFIG": "/etc/autophagy/site-mail-backend.json",
    }
    environment.update(overrides)
    return environment
