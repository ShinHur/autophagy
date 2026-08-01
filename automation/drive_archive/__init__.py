"""Drive archive: mirror tracked project deliverables into the owner's own Google Drive.

Batch-digest owner approval (reuses ``automation.interop.external_effect_gate``)
gates every upload; the effect runs the existing ``gws drive`` CLI. Runtime
state (cursor, pending batches, approval log, folder-id cache, receipts) lives
OUTSIDE the checkout — tracked files are never mutated at runtime.
"""

from __future__ import annotations
