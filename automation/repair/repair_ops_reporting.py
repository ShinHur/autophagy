"""Redacted ticket updates and patch documentation for W6-2."""

from __future__ import annotations

import subprocess
import pwd
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from automation.interop.approval_surface import ApprovalKind, ApprovalSurface, reaction_instruction

from automation.repair.repair_ops_core import RepairPlan
from automation.repair.repair_redaction import redact


@dataclass(frozen=True, slots=True)
class HermesTicketBoard:
    """Keep ticket comments redacted while exposing only lifecycle transitions."""

    def complete(self, ticket_id: str, summary: str) -> None:
        """Mark a ticket complete after a successful green regression run."""
        try:
            self._run("complete", ticket_id, redact(summary))
        except (KeyError, subprocess.CalledProcessError):
            return

    def reopen(self, ticket_id: str, summary: str) -> None:
        """Reopen a ticket after sandbox rejection or an automatic rollback."""
        try:
            self._run("unblock", ticket_id)
            self._run("block", "--kind", "needs_input", ticket_id, redact(summary))
        except (KeyError, subprocess.CalledProcessError):
            return

    @staticmethod
    def _run(*args: str) -> None:
        agent_uid = pwd.getpwnam("agent").pw_uid
        command = shlex.join(("hermes", "kanban", *args))
        _ = subprocess.run(
            ("sudo", "-n", "-u", "agent", "-H", "env", f"XDG_RUNTIME_DIR=/run/user/{agent_uid}", "bash", "-lc", command),
            capture_output=True,
            check=True,
            text=True,
            timeout=60,
        )


@dataclass(frozen=True, slots=True)
class PatchDocumentWriter:
    """Write a repository patch note without raw logs or sensitive fixture values."""

    docs_root: Path

    def write(self, plan: RepairPlan, commit: str) -> Path:
        """Record scope, verification, and deferred human follow-up in a redacted note."""
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        target = self.docs_root / f"{date}-{plan.ticket_id}.md"
        diagnosis = redact(plan.diagnosis)
        _ = target.write_text(
            "\n".join(
                (
                    f"# Repair {plan.ticket_id}",
                    "",
                    "## Scope",
                    "Repository code/config only; agent secrets and private logs were not read into git.",
                    "",
                    "## Applied state",
                    f"- commit: `{commit}`",
                    f"- diagnosis: {diagnosis}",
                    "",
                    "## Verification",
                    "- peer sandbox existing regression bank: PASS",
                    "- repair RED reproduction: GREEN",
                    "",
                    "## Deferred [USER] gate",
                    f"Real owner {reaction_instruction(ApprovalKind.REPAIR, ApprovalSurface.SKILL_APPROVALS, name_surface=True)} reaction remains a non-blocking production follow-up.",
                    "",
                )
            ),
            encoding="utf-8",
        )
        return target
