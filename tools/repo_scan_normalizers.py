from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from collections import deque
from typing import Final
from urllib.parse import unquote

from repo_scan_models import TextView


_JSON_ESCAPE: Final = re.compile(r"\\u([0-9A-Fa-f]{4})")
_BASE64_RUN: Final = re.compile(r"(?<![A-Za-z0-9+/_=-])[A-Za-z0-9+/_-]{20,}={0,2}(?![A-Za-z0-9+/_=-])")
_MAX_VIEWS: Final = 256


def generic_views(text: str) -> tuple[TextView, ...]:
    """Return normalized views including URL, JSON, and Base64 decodings."""
    queue = deque((TextView(text),))
    views: list[TextView] = []
    seen: set[str] = set()
    while queue and len(views) < _MAX_VIEWS:
        view = queue.popleft()
        normalized = unicodedata.normalize("NFC", view.text)
        if normalized in seen:
            continue
        seen.add(normalized)
        current = TextView(normalized, view.source_line)
        views.append(current)
        for transformed in (unquote(normalized), _decode_json_escapes(normalized)):
            if transformed != normalized and transformed not in seen:
                queue.append(TextView(transformed, view.source_line))
        for match in _BASE64_RUN.finditer(normalized):
            decoded = _decode_base64(match.group(0))
            if decoded is not None and decoded not in seen:
                source_line = view.source_line or normalized.count("\n", 0, match.start()) + 1
                queue.append(TextView(decoded, source_line))
    return tuple(views)


def _decode_json_escapes(text: str) -> str:
    return _JSON_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), text)


def _decode_base64(token: str) -> str | None:
    padding = "=" * (-len(token) % 4)
    try:
        decoded = base64.b64decode(token + padding, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        return None
    try:
        return decoded.decode("utf-8")
    except UnicodeDecodeError:
        return decoded.decode("latin-1")
