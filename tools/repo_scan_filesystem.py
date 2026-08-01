from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# Derived artifacts a build or test run regenerates. They are ignored by version
# control, so they can never reach a published tree — scanning them only produces
# findings that appear and vanish with the last test run. A gate that fails 600
# times on the ordinary "run the tests, then run the gate" workflow is a gate
# contributors learn to skip, so these are excluded by construction rather than
# by an allowlist. Source is never excluded.
_DERIVED_DIRECTORIES: Final = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tox",
        ".venv",
        "node_modules",
        ".codegraph",
    }
)
_DERIVED_SUFFIXES: Final = (".pyc", ".pyo", ".pyd")


def is_derived_artifact(path: Path) -> bool:
    """Whether ``path`` is a build or test artifact rather than repository source."""
    if any(part in _DERIVED_DIRECTORIES for part in path.parts):
        return True
    return path.suffix in _DERIVED_SUFFIXES


@dataclass(frozen=True, slots=True)
class WalkResult:
    paths: tuple[Path, ...]
    errors: tuple[Path, ...]


def selected_paths(root: Path) -> WalkResult:
    paths: list[Path] = []
    errors: list[Path] = []

    def on_error(_error: OSError) -> None:
        errors.append(root)

    for current, directories, files in os.walk(root, followlinks=False, onerror=on_error):
        directories[:] = sorted(
            name for name in directories if name not in _DERIVED_DIRECTORIES
        )
        current_path = Path(current)
        paths.extend(current_path / name for name in directories)
        paths.extend(
            current_path / name
            for name in sorted(files)
            if not name.endswith(_DERIVED_SUFFIXES)
        )
    return WalkResult(tuple(paths), tuple(errors))
