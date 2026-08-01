"""Gate-binding + denylist-rule + procurement-regression specs (E11 S2).

Drives the REAL ``automation.interop.external_effect_gate`` as a library so the
batch action_hash is computed by the production gate, and locks that adding our
rule leaves procurement's ``gws drive +upload`` path untouched.
"""

from __future__ import annotations

from automation.drive_archive import gate_binding, manifest
from automation.interop import external_effect_gate as gate
from automation.interop.external_effect_gate import ApprovalContext, ToolCall, load_denylist

RULE_ID = "drive_archive_batch_upload"


def _manifest() -> manifest.BatchManifest:
    return manifest.BatchManifest(
        "autophagy",
        (
            manifest.FileEntry("docs/features.md", "a" * 64),
            manifest.FileEntry(".omo/plans/a.md", "b" * 64),
        ),
    )


def _denylist() -> tuple[gate.ExternalEffectRule, ...]:
    return load_denylist(gate_binding.denylist_path())


def test_action_hash_matches_real_gate() -> None:
    built = _manifest()
    call = gate_binding.build_tool_call(built)
    assert call.tool_name == "drive_archive.batch_upload"

    target = f"tool:{RULE_ID}:{gate_binding.TOOL_NAME}"
    expected = gate._action_hash(call, target)
    decision = gate_binding.evaluate(built, context=ApprovalContext(None, "owner", False))

    assert decision.external_effect is True
    assert decision.allowed is False  # no approval record present
    assert decision.target_id == target
    assert decision.action_hash == expected


def test_manifest_mutation_changes_hash() -> None:
    built = _manifest()
    base = gate_binding.evaluate(built, context=ApprovalContext(None, "o", False))
    mutated = manifest.BatchManifest(
        built.project, (*built.files, manifest.FileEntry("x.md", "c" * 64))
    )
    other = gate_binding.evaluate(mutated, context=ApprovalContext(None, "o", False))
    assert other.action_hash != base.action_hash


def test_denylist_rule_matches_our_tool() -> None:
    call = gate_binding.build_tool_call(_manifest())
    decision = gate.evaluate_tool_call(call, _denylist(), ApprovalContext(None, "o", False))
    assert decision.external_effect is True


def test_procurement_gws_upload_stays_unmatched() -> None:
    call = ToolCall(
        tool_name="bash",
        arguments={"command": "gws drive +upload out/large.hwpx --parent FOLDER --name large.hwpx"},
    )
    decision = gate.evaluate_tool_call(call, _denylist(), ApprovalContext(None, "o", False))
    assert decision.external_effect is False


def test_patent_draft_upload_still_gated() -> None:
    call = ToolCall(
        tool_name="gws",
        arguments={"command": "gws drive +upload /x/patent-drafts/foo.hwpx"},
    )
    decision = gate.evaluate_tool_call(call, _denylist(), ApprovalContext(None, "o", False))
    assert decision.external_effect is True
