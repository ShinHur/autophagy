"""Minimal stdlib client for the W2-1 FastMCP memory server (Streamable HTTP).

Protocol for the configured MCP endpoint:
  1. POST {base}/mcp/ ``initialize``      -> SSE body + ``mcp-session-id`` header
  2. POST ``notifications/initialized``   -> 202
  3. POST ``tools/call``                  -> SSE ``data:`` line with JSON-RPC result

Uses only ``urllib`` so the ingest path has a single, auditable network choke
point. Every connection target is appended to ``network_log`` — the ingest log
records it, and the external-embedding-API==0 proof is additionally taken with
an OS-level ``strace`` capture during QA.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

_PROTOCOL_VERSION = "2025-06-18"
_TIMEOUT_SECONDS = 30.0


class McpUnreachableError(Exception):
    """RAG node down / connection refused / 5xx — retryable, keep queued."""


class McpFatalError(Exception):
    """Auth or protocol failure — not retryable without operator action."""


@dataclass
class McpMemoryClient:
    base_url: str
    api_key: str
    network_log: list[str] = field(default_factory=list)
    _session_id: str | None = field(default=None, init=False)
    _next_id: int = field(default=1, init=False)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id is not None:
            headers["mcp-session-id"] = self._session_id
        return headers

    def _post(self, payload: dict[str, Any]) -> tuple[int, dict[str, str], str]:
        url = f"{self.base_url.rstrip('/')}/mcp/"
        self.network_log.append(url)
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8", errors="replace")
                headers = {k.lower(): v for k, v in response.headers.items()}
                return response.status, headers, body
        except urllib.error.HTTPError as error:
            if error.code in (401, 403):
                raise McpFatalError(f"MCP auth rejected: HTTP {error.code}") from error
            raise McpUnreachableError(f"MCP HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            raise McpUnreachableError(f"MCP unreachable: {error}") from error

    @staticmethod
    def _parse_sse_result(body: str, request_id: int) -> dict[str, Any]:
        for line in body.splitlines():
            if not line.startswith("data:"):
                continue
            message = json.loads(line[len("data:") :].strip())
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise McpFatalError(f"MCP JSON-RPC error: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise McpFatalError("MCP result missing or malformed")
            return result
        raise McpFatalError("no matching SSE data frame in MCP response")

    def connect(self) -> None:
        request_id = self._next_id
        self._next_id += 1
        _status, headers, body = self._post(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "rag-ingest", "version": "1.0.0"},
                },
            }
        )
        session_id = headers.get("mcp-session-id")
        if not session_id:
            raise McpFatalError("initialize returned no mcp-session-id header")
        _ = self._parse_sse_result(body, request_id)
        self._session_id = session_id
        _status2, _headers2, _body2 = self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )

    def _ensure_connected(self) -> None:
        if self._session_id is None:
            self.connect()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self._ensure_connected()
        request_id = self._next_id
        self._next_id += 1
        _status, _headers, body = self._post(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        result = self._parse_sse_result(body, request_id)
        if result.get("isError"):
            raise McpFatalError(f"tool {name} returned isError: {result.get('content')}")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured.get("result", structured)
        return result

    def load_memory(
        self, content: str, source: str, metadata: dict[str, str]
    ) -> dict[str, Any]:
        loaded = self.call_tool(
            "load_memory",
            {"content": content, "source": source, "metadata": metadata},
        )
        if not isinstance(loaded, dict):
            raise McpFatalError("load_memory returned non-dict result")
        return loaded

    def search_memory(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        found = self.call_tool("search_memory", {"query": query, "limit": limit})
        if not isinstance(found, list):
            raise McpFatalError("search_memory returned non-list result")
        return found

    def delete_memory(self, document_id: str) -> dict[str, Any]:
        deleted = self.call_tool("delete_memory", {"document_id": document_id})
        if not isinstance(deleted, dict):
            raise McpFatalError("delete_memory returned non-dict result")
        return deleted
