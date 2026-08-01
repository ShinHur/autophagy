#!/usr/bin/env python3
# noqa: SIZE_OK — the authorized single-file bridge keeps its typed wire contract beside execution.
from __future__ import annotations

import argparse
import builtins
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Final, Literal, TypeAlias, assert_never

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
Operation: TypeAlias = Literal["list", "get", "status", "resolve", "send"]

CONTRACT_VERSION: Final = 1
_CONFIG_FIELDS: Final = frozenset(
    {"contract_version", "backend_id", "organization", "command", "timeout_seconds"}
)
_PLACEHOLDER = re.compile(
    r"(?:\{\{[^{}]+\}\}|\$\{[^{}]+\}|<[^<>]+>|\b(?:CHANGE_ME|REPLACE_ME|TODO|TBD)\b|\bYOUR_[A-Z0-9_]+\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class BackendUnavailable(RuntimeError):
    reason: str

    def __str__(self) -> str:
        return f"site mail backend unavailable: {self.reason}"


@dataclass(frozen=True, slots=True)
class BackendConfig:
    contract_version: int
    backend_id: str
    organization: str
    command: tuple[str, ...]
    timeout_seconds: int


@dataclass(frozen=True, slots=True)
class MailSummary:
    message_id: str
    folder: str
    subject: str
    sender: str
    received_at: str


@dataclass(frozen=True, slots=True)
class MailDetail:
    message_id: str
    folder: str
    subject: str
    sender: str
    received_at: str
    body: str | None


@dataclass(frozen=True, slots=True)
class ResolveCandidate:
    kind: str
    name: str
    email: str
    organization: str


@dataclass(frozen=True, slots=True)
class Attachment:
    source_path: str
    filename: str
    size_bytes: int
    mime_type: str
    sha256: str

    def to_json(self) -> JsonObject:
        return {
            "source_path": self.source_path,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "mime_type": self.mime_type,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ListRequest:
    limit: int
    sync: bool
    operation: Literal["list"] = field(default="list", init=False)

    def to_json(self) -> JsonObject:
        return {"operation": self.operation, "limit": self.limit, "sync": self.sync}


@dataclass(frozen=True, slots=True)
class GetRequest:
    message_id: str
    include_body: bool
    operation: Literal["get"] = field(default="get", init=False)

    def to_json(self) -> JsonObject:
        return {
            "operation": self.operation,
            "message_id": self.message_id,
            "include_body": self.include_body,
        }


@dataclass(frozen=True, slots=True)
class StatusRequest:
    operation: Literal["status"] = field(default="status", init=False)

    def to_json(self) -> JsonObject:
        return {"operation": self.operation}


@dataclass(frozen=True, slots=True)
class ResolveRequest:
    query: str
    operation: Literal["resolve"] = field(default="resolve", init=False)

    def to_json(self) -> JsonObject:
        return {"operation": self.operation, "query": self.query}


@dataclass(frozen=True, slots=True)
class SendRequest:
    to: str
    subject: str
    body: str
    attachments: tuple[Attachment, ...]
    attachment_manifest_sha256: str | None
    operation: Literal["send"] = field(default="send", init=False)

    def to_json(self) -> JsonObject:
        return {
            "operation": self.operation,
            "to": self.to,
            "subject": self.subject,
            "body": self.body,
            "attachments": [attachment.to_json() for attachment in self.attachments],
            "attachment_manifest_sha256": self.attachment_manifest_sha256,
        }


Request: TypeAlias = ListRequest | GetRequest | StatusRequest | ResolveRequest | SendRequest


@dataclass(frozen=True, slots=True)
class ListResponse:
    operation: Literal["list"]
    status: Literal["ok"]
    synced: bool
    mails: tuple[MailSummary, ...]


@dataclass(frozen=True, slots=True)
class GetResponse:
    operation: Literal["get"]
    status: Literal["ok"]
    mail: MailDetail


@dataclass(frozen=True, slots=True)
class StatusResponse:
    operation: Literal["status"]
    status: Literal["ok"]
    available: bool
    account: str
    message: str


@dataclass(frozen=True, slots=True)
class ResolveResponse:
    operation: Literal["resolve"]
    status: Literal["ok"]
    query: str
    candidates: tuple[ResolveCandidate, ...]


@dataclass(frozen=True, slots=True)
class SendResponse:
    operation: Literal["send"]
    status: Literal["submitted"]
    message_id: str
    verified: bool
    attachment_count: int
    attachment_manifest_sha256: str | None


Response: TypeAlias = ListResponse | GetResponse | StatusResponse | ResolveResponse | SendResponse


def _config_env() -> ModuleType:
    roots = [Path(os.environ["AUTOPHAGY_REPO_ROOT"])] if os.environ.get("AUTOPHAGY_REPO_ROOT") else []
    roots.append(Path(__file__).resolve().parents[3])
    for root in roots:
        if (root / "automation" / "config_env.py").is_file() and str(root) not in sys.path:
            sys.path.insert(0, str(root))
    try:
        from automation import config_env
    except ImportError as error:
        raise BackendUnavailable("configuration accessor is unavailable") from error
    return config_env


def _load_config() -> tuple[BackendConfig, str]:
    config_env = _config_env()
    try:
        path = config_env.site_mail_backend_config()
    except config_env.ConfigError as error:
        raise BackendUnavailable("SITE_MAIL_BACKEND_CONFIG is not configured") from error
    try:
        raw: JsonValue = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BackendUnavailable("backend config cannot be read as JSON") from error
    payload = _json_object(raw, "config")
    if frozenset(payload) != _CONFIG_FIELDS:
        raise BackendUnavailable("backend config fields do not match the contract")
    _reject_placeholders(payload)
    version = _integer(payload, "contract_version")
    command_raw = payload["command"]
    if not isinstance(command_raw, builtins.list) or not command_raw:
        raise BackendUnavailable("command must be a non-empty JSON array")
    if not all(isinstance(item, str) and item for item in command_raw):
        raise BackendUnavailable("command entries must be non-empty strings")
    command = tuple(command_raw)
    timeout = _integer(payload, "timeout_seconds")
    if version != CONTRACT_VERSION or not Path(command[0]).is_absolute() or not 1 <= timeout <= 3600:
        raise BackendUnavailable("backend config version, command, or timeout is invalid")
    canonical = _canonical_json(payload)
    return (
        BackendConfig(version, _string(payload, "backend_id"), _string(payload, "organization"), command, timeout),
        f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}",
    )


def config_sha256() -> str:
    return _load_config()[1]


def verify_config_sha256(expected: str) -> None:
    current = config_sha256()
    if current != expected:
        raise BackendUnavailable("backend config hash changed after approval")


def list(request: ListRequest) -> ListResponse:
    return _parse_list(_invoke(request))


def get(request: GetRequest) -> GetResponse:
    return _parse_get(_invoke(request))


def status(request: StatusRequest) -> StatusResponse:
    return _parse_status(_invoke(request))


def resolve(request: ResolveRequest) -> ResolveResponse:
    return _parse_resolve(_invoke(request))


def send(request: SendRequest, *, expected_config_sha256: str) -> SendResponse:
    config, current_hash = _load_config()
    if current_hash != expected_config_sha256:
        raise BackendUnavailable("backend config hash changed after approval")
    return _parse_send(_invoke_with_config(request, config))


def build_send_argv(request: SendRequest, expected_config_sha256: str) -> tuple[str, ...]:
    return (
        sys.executable,
        str(Path(__file__).resolve()),
        "send",
        "--expected-config-sha256",
        expected_config_sha256,
        "--request-json",
        _canonical_json(request.to_json()),
    )


def _invoke(request: Request) -> JsonObject:
    config, _config_hash = _load_config()
    return _invoke_with_config(request, config)


def _invoke_with_config(request: Request, config: BackendConfig) -> JsonObject:
    try:
        process = subprocess.run(
            builtins.list(config.command),
            input=_canonical_json(request.to_json()),
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            check=False,
            env=dict(os.environ),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise BackendUnavailable("backend process could not complete") from error
    try:
        raw: JsonValue = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise BackendUnavailable("backend response is not JSON") from error
    payload = _json_object(raw, "response")
    if process.returncode != 0 or payload.get("status") == "error":
        raise BackendUnavailable("backend returned an error response")
    return payload


def _parse_list(payload: JsonObject) -> ListResponse:
    _success(payload, "list", "ok")
    raw_mails = _array(payload, "mails")
    return ListResponse("list", "ok", _boolean(payload, "synced"), tuple(_mail(item) for item in raw_mails))


def _parse_get(payload: JsonObject) -> GetResponse:
    _success(payload, "get", "ok")
    raw = _json_object(payload.get("mail"), "mail")
    summary = _mail(raw)
    body = raw.get("body")
    if body is not None and not isinstance(body, str):
        raise BackendUnavailable("mail.body must be a string or null")
    return GetResponse(
        "get",
        "ok",
        MailDetail(
            summary.message_id,
            summary.folder,
            summary.subject,
            summary.sender,
            summary.received_at,
            body,
        ),
    )


def _parse_status(payload: JsonObject) -> StatusResponse:
    _success(payload, "status", "ok")
    return StatusResponse(
        "status", "ok", _boolean(payload, "available"), _string(payload, "account"), _string(payload, "message")
    )


def _parse_resolve(payload: JsonObject) -> ResolveResponse:
    _success(payload, "resolve", "ok")
    candidates = []
    for value in _array(payload, "candidates"):
        item = _json_object(value, "candidate")
        candidates.append(
            ResolveCandidate(
                _string(item, "kind"),
                _string(item, "name"),
                _string(item, "email"),
                _string(item, "organization"),
            )
        )
    return ResolveResponse("resolve", "ok", _string(payload, "query"), tuple(candidates))


def _parse_send(payload: JsonObject) -> SendResponse:
    _success(payload, "send", "submitted")
    manifest = payload.get("attachment_manifest_sha256")
    if manifest is not None and not isinstance(manifest, str):
        raise BackendUnavailable("attachment_manifest_sha256 must be a string or null")
    return SendResponse(
        "send", "submitted", _string(payload, "message_id"), _boolean(payload, "verified"),
        _integer(payload, "attachment_count"), manifest,
    )


def _mail(value: JsonValue) -> MailSummary:
    payload = _json_object(value, "mail")
    return MailSummary(*(_string(payload, key) for key in ("message_id", "folder", "subject", "sender", "received_at")))


def _success(payload: JsonObject, operation: Operation, status_value: str) -> None:
    if payload.get("operation") != operation or payload.get("status") != status_value:
        raise BackendUnavailable("backend response operation or status is invalid")


def _json_object(value: JsonValue, field_name: str) -> JsonObject:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise BackendUnavailable(f"{field_name} must be a JSON object")
    return value


def _array(payload: JsonObject, key: str) -> tuple[JsonValue, ...]:
    value = payload.get(key)
    if not isinstance(value, builtins.list):
        raise BackendUnavailable(f"{key} must be a JSON array")
    return tuple(value)


def _string(payload: JsonObject, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise BackendUnavailable(f"{key} must be a non-empty string")
    return value


def _integer(payload: JsonObject, key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BackendUnavailable(f"{key} must be an integer")
    return value


def _boolean(payload: JsonObject, key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise BackendUnavailable(f"{key} must be a boolean")
    return value


def _reject_placeholders(value: JsonValue) -> None:
    match value:
        case str() as text:
            if _PLACEHOLDER.search(text):
                raise BackendUnavailable("backend config contains a template placeholder")
        case builtins.list() as items:
            for item in items:
                _reject_placeholders(item)
        case dict() as mapping:
            for item in mapping.values():
                _reject_placeholders(item)
        case int() | float() | bool() | None:
            return
        case unreachable:
            assert_never(unreachable)


def _canonical_json(payload: JsonObject) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _request(operation: Operation, raw: str) -> Request:
    try:
        payload = _json_object(json.loads(raw), "request")
    except json.JSONDecodeError as error:
        raise BackendUnavailable("request is not JSON") from error
    if payload.get("operation") != operation:
        raise BackendUnavailable("request operation does not match the bridge command")
    match operation:
        case "list":
            return ListRequest(_integer(payload, "limit"), _boolean(payload, "sync"))
        case "get":
            return GetRequest(_string(payload, "message_id"), _boolean(payload, "include_body"))
        case "status":
            return StatusRequest()
        case "resolve":
            return ResolveRequest(_string(payload, "query"))
        case "send":
            attachments = []
            for value in _array(payload, "attachments"):
                item = _json_object(value, "attachment")
                attachments.append(
                    Attachment(
                        _string(item, "source_path"),
                        _string(item, "filename"),
                        _integer(item, "size_bytes"),
                        _string(item, "mime_type"),
                        _string(item, "sha256"),
                    )
                )
            manifest = payload.get("attachment_manifest_sha256")
            if manifest is not None and not isinstance(manifest, str):
                raise BackendUnavailable("attachment_manifest_sha256 must be a string or null")
            return SendRequest(
                _string(payload, "to"),
                _string(payload, "subject"),
                _string(payload, "body"),
                tuple(attachments),
                manifest,
            )
        case unreachable:
            assert_never(unreachable)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="site_mail_backend.py")
    parser.add_argument("operation", choices=("list", "get", "status", "resolve", "send"))
    parser.add_argument("--request-json", required=True)
    parser.add_argument("--expected-config-sha256")
    args = parser.parse_args(argv)
    try:
        request = _request(args.operation, args.request_json)
        match request:
            case ListRequest():
                response: Response = list(request)
            case GetRequest():
                response = get(request)
            case StatusRequest():
                response = status(request)
            case ResolveRequest():
                response = resolve(request)
            case SendRequest():
                expected = args.expected_config_sha256
                if not isinstance(expected, str) or not expected:
                    raise BackendUnavailable("send requires the approved config hash")
                response = send(request, expected_config_sha256=expected)
            case unreachable:
                assert_never(unreachable)
    except BackendUnavailable:
        print(
            _canonical_json(
                {
                    "operation": args.operation,
                    "status": "error",
                    "error_code": "backend_unavailable",
                    "message": "site backend unavailable",
                    "retryable": False,
                    "stage": "bridge",
                }
            )
        )
        return 6
    encoded: JsonObject = asdict(response)
    print(_canonical_json(encoded))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
