"""Mounted skills must accept a parameterized immutable code root.

A mounted skill resolves where shared ``automation.*`` / repo code lives in
order to import it. The root is deployment configuration, not a source literal:
an immutable release can therefore be selected ahead of a mutable checkout.
This inventory test keeps every resolver on an explicit configuration contract.

NOT in scope: approval-log / config-seed paths under the checkout
(``*_gate.py``, ``triage_mode.py``, ``calendar_routing.py``) — those are runtime
state locations, not code roots, and are a separate concern.
"""
from __future__ import annotations

from pathlib import Path
_REPO = Path(__file__).resolve().parents[2]

# The code-root resolvers migrated by W3.C (path, the function that resolves the root).
_CODE_ROOT_RESOLVERS = (
    "skills/mail/scripts/mail_preflight.py",
    "skills/calendar/scripts/calendar_preflight.py",
    "skills/todo/scripts/todo_preflight.py",
    "skills/doctype/scripts/doctype_store.py",
    "skills/prompt/scripts/prompt_store.py",
    "skills/wiki/scripts/wiki_confirm_reaction_watch.py",
)


def test_all_code_root_resolvers_exist() -> None:
    for rel in _CODE_ROOT_RESOLVERS:
        assert (_REPO / rel).is_file(), rel


def test_every_skill_code_root_resolver_accepts_a_configured_release_root() -> None:
    offenders: list[str] = []
    for rel in _CODE_ROOT_RESOLVERS:
        text = (_REPO / rel).read_text(encoding="utf-8")
        contracts = (
            "AUTOPHAGY_REPO_ROOT",
            "DOCTYPE_REPO_ROOT",
            "PROMPT_REPO_ROOT",
            "config_env.deploy_root",
        )
        if not any(contract in text for contract in contracts):
            offenders.append(f"{rel}: has no parameterized code-root contract")
    assert not offenders, "skill code-root resolvers lack a configurable release root:\n" + "\n".join(offenders)
