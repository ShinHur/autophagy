"""Static inventory locks for the owner-approval surface (AS-0.2, item (j)).

Split out of ``test_approval_surface_characterization.py`` to keep both files
small. The sets below are what a full AST scan of the deployed tree
(``skills/*/scripts/*.py`` + ``automation/**/*.py``) actually finds today, so a
newly added resolver, DM opener, or env override anywhere fails these tests. The
walk and the source glob are the shared ones in ``approval_conformance_ast``
(AS-1.11); this file keeps no private copy of either.

AS-1.x migrated EVERY approval flow onto the shared directory
``automation/interop/approval_directory.py``. Each one now reaches it through its
own binding adapter — ``triage_binding`` / ``budget_binding`` /
``patent_export_binding._directory`` / ``drive_archive.approval_binding`` /
``repair_ops_binding`` / ``calendar_binding`` / ``coordination_binding`` /
``wiki_binding`` / ``skill_gate_surface`` — so no flow defines an
``approvals_channel_id`` resolver or opens the owner DM itself any more. AS-3.2
then removed the five per-flow env overrides those adapters used to carry.

approvals-channel resolver definitions (1 — the shared config accessor; no flow
resolves its own channel):
  automation/config_env.py:96                                   discord_approvals_channel_id

owner-DM openers, i.e. sites naming ``/users/@me/channels`` (8 — the central
directory plus the seven DM senders it deliberately does NOT own; not one of the
seven is an approval path):
  skills/procurement/scripts/procure_review.py:67       send_review
  automation/cost-report/send_cost_report.py:176        send_dm
  automation/interop/gate_driver.py:83                  main
  automation/interop/hermes_plugin/__init__.py:189      _send_direct_result
  automation/reminder_poller/poll_reminders.py:165      DmSender.send
  automation/research_trends/research_trends.py:254     _send_dm
  automation/memory_curator/effects.py:71               alert_owner  (near-cap notice, not an approval)
  automation/interop/approval_directory.py:27           <module>  (AS-1.2 central directory)

``*_APPROVALS_CHANNEL_ID`` env overrides (1 — the shared config accessor's
deployment input; no flow may read it directly):
  automation/config_env.py:97                                   DISCORD_APPROVALS_CHANNEL_ID
"""
from __future__ import annotations

import ast
from typing import Final

from approval_conformance_ast import _deployed_sources, _qualnames
from approval_conformance_inventory import _REPO

_DM_PATH: Final = "/users/@me/channels"
_DIRECTORY: Final = "automation/interop/approval_directory.py"

# The shared configuration accessor is the only non-flow resolver; all approval
# flows must reach it through the directory and their binding adapter.
_KNOWN_RESOLVERS: Final = frozenset({
    "automation/config_env.py::discord_approvals_channel_id",
})

_KNOWN_DM_OPENERS: Final = frozenset({
    "skills/procurement/scripts/procure_review.py::send_review",
    "automation/cost-report/send_cost_report.py::send_dm",
    "automation/interop/gate_driver.py::main",
    "automation/interop/hermes_plugin/__init__.py::_send_direct_result",
    "automation/reminder_poller/poll_reminders.py::DmSender.send",
    "automation/research_trends/research_trends.py::_send_dm",
    "automation/memory_curator/effects.py::alert_owner",
    # The central directory (AS-1.2). Every flow resolves through it, so this is
    # the one opener the migration was meant to add — and the only one left that
    # an approval can reach.
    f"{_DIRECTORY}::<module>",
})

# The shared configuration accessor owns the sole deployment env read. Any flow
# bypassing that boundary appears as an additional AST hit and fails this lock.
_KNOWN_ENV_OVERRIDES: Final = frozenset({
    "automation/config_env.py::DISCORD_APPROVALS_CHANNEL_ID",
})


def _scan_source(
    relative: str,
    tree: ast.Module,
) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(resolver defs, owner-DM opener sites, env overrides) found in ONE parsed source."""
    resolvers: set[str] = set()
    openers: set[str] = set()
    overrides: set[str] = set()
    scopes: list[tuple[str, ast.AST]] = [
        (qualname, node)
        for qualname, node in _qualnames(tree).items()
        if not isinstance(node, ast.ClassDef)
    ]
    # A module-level constant belongs to no function, so scanning only function
    # scopes would let any caller dodge this inventory by hoisting the path into
    # a module Final. Scan the module body itself as the "<module>" scope.
    scopes.extend(
        ("<module>", statement)
        for statement in tree.body
        if not isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    )
    for qualname, node in scopes:
        if qualname.split(".")[-1].endswith("approvals_channel_id"):
            resolvers.add(f"{relative}::{qualname}")
        for child in ast.walk(node):
            if not isinstance(child, ast.Constant) or not isinstance(child.value, str):
                continue
            if _DM_PATH in child.value:
                openers.add(f"{relative}::{qualname}")
            if child.value.endswith("_APPROVALS_CHANNEL_ID"):
                overrides.add(f"{relative}::{child.value}")
    return frozenset(resolvers), frozenset(openers), frozenset(overrides)


def _scan() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """The same scan unioned over the whole deployed tree."""
    resolvers: set[str] = set()
    openers: set[str] = set()
    overrides: set[str] = set()
    for path in _deployed_sources():
        relative = str(path.relative_to(_REPO))
        found_resolvers, found_openers, found_overrides = _scan_source(
            relative, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
        resolvers |= found_resolvers
        openers |= found_openers
        overrides |= found_overrides
    return frozenset(resolvers), frozenset(openers), frozenset(overrides)


def test_no_flow_defines_its_own_approvals_channel_resolver() -> None:
    # Given / When: every `*approvals_channel_id` definition in the deployed tree.
    resolvers, _, _ = _scan()

    # Then: SI-2 is complete — only the shared config accessor resolves the deployment
    # input, so any flow-local resolver has to be a deliberate diff against this lock.
    assert resolvers == _KNOWN_RESOLVERS
    assert "DiscordChannelDirectory.skill_approvals" in _qualnames(
        ast.parse((_REPO / _DIRECTORY).read_text(encoding="utf-8"), filename=_DIRECTORY)
    )


def test_owner_dm_openers_are_only_the_directory_and_non_approval_senders_today() -> None:
    # Given / When: every function naming the DM-open REST path.
    _, openers, _ = _scan()

    # Then: SI-2 has collapsed every approval flow into that one directory. What is
    # left is the directory plus seven DM senders it deliberately does NOT own — a
    # procurement review, a cost report, the gate driver, the plugin's direct
    # result, the reminder poller, the trends digest, the curator near-cap notice —
    # none of them an approval, and none able to become one without failing this lock.
    assert openers == _KNOWN_DM_OPENERS
    assert f"{_DIRECTORY}::<module>" in openers
    assert len(openers) == 8


def test_no_flow_reads_an_approvals_channel_env_override_after_r3() -> None:
    # Given / When: every `*_APPROVALS_CHANNEL_ID` name read in the deployed tree.
    _, _, overrides = _scan()

    # Then: only the shared config accessor names the deployment env input; no
    # approval flow may read an override directly.
    assert overrides == _KNOWN_ENV_OVERRIDES

    # And: that emptiness is a fact about the tree, not a scanner that stopped
    # looking. The same scan still reports a re-introduced override, so this lock
    # cannot rot into a no-op.
    reintroduced = "skills/demo/scripts/demo_binding.py"
    _, _, regression = _scan_source(
        reintroduced, ast.parse('OVERRIDE: Final = "DEMO_APPROVALS_CHANNEL_ID"\n')
    )
    assert regression == frozenset({f"{reintroduced}::DEMO_APPROVALS_CHANNEL_ID"})
