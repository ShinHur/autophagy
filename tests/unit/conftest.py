from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from tests.unit._synthetic import synthetic_env


@pytest.fixture(autouse=True)
def _synthetic_configuration(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in synthetic_env().items():
        if name not in os.environ:
            monkeypatch.setenv(name, value)
    yield
