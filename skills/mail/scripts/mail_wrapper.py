#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os

import site_mail_backend
from mail_wrapper_classification import classify_metadata
from mail_wrapper_read import mask_value, render_detail, render_summary

WRAPPER_VERSION = "mail-wrapper-v2"
_EXIT = {"backend_unavailable": 3, "not_found": 5, "usage_error": 4}


def _emit(payload: site_mail_backend.JsonObject, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return exit_code


def _error(command: str, error_code: str, guidance: str) -> int:
    return _emit(
        {
            "wrapper": WRAPPER_VERSION,
            "command": command,
            "status": "error",
            "error_code": error_code,
            "guidance": guidance,
        },
        _EXIT[error_code],
    )


def _salt() -> str:
    return os.environ.get("MAIL_WRAPPER_MASK_SALT", "")


def cmd_list(args: argparse.Namespace) -> int:
    response = site_mail_backend.list(
        site_mail_backend.ListRequest(limit=args.limit, sync=args.sync)
    )
    if not response.mails:
        return _error("list", "not_found", "site backend returned no messages")
    return _emit(
        {
            "wrapper": WRAPPER_VERSION,
            "command": "list",
            "status": "ok",
            "masked": args.masked,
            "synced": response.synced,
            "count": len(response.mails),
            "mails": [
                render_summary(mail, masked=args.masked, salt=_salt())
                for mail in response.mails
            ],
        }
    )


def cmd_get(args: argparse.Namespace) -> int:
    response = site_mail_backend.get(
        site_mail_backend.GetRequest(message_id=args.uid, include_body=args.body)
    )
    return _emit(
        {
            "wrapper": WRAPPER_VERSION,
            "command": "get",
            "status": "ok",
            "masked": args.masked,
            "mail": render_detail(
                response.mail,
                masked=args.masked,
                salt=_salt(),
                include_body=args.body,
            ),
        }
    )


def cmd_classify(args: argparse.Namespace) -> int:
    if args.uid:
        response = site_mail_backend.get(
            site_mail_backend.GetRequest(message_id=args.uid, include_body=False)
        )
        subject, sender = response.mail.subject, response.mail.sender
        reference: site_mail_backend.JsonObject = {"uid": args.uid}
    else:
        subject, sender = args.subject or "", args.sender or ""
        reference = {}
    if args.masked:
        reference.update(
            subject=mask_value(subject, _salt()), sender=mask_value(sender, _salt())
        )
    return _emit(
        {
            "wrapper": WRAPPER_VERSION,
            "command": "classify",
            "status": "ok",
            "masked": args.masked,
            **reference,
            "classification": classify_metadata(subject, sender),
        }
    )


def cmd_status(_args: argparse.Namespace) -> int:
    response = site_mail_backend.status(site_mail_backend.StatusRequest())
    return _emit(
        {
            "wrapper": WRAPPER_VERSION,
            "command": "status",
            "status": "ok",
            "available": response.available,
            "account": response.account,
            "message": response.message,
        }
    )


def cmd_resolve(args: argparse.Namespace) -> int:
    response = site_mail_backend.resolve(site_mail_backend.ResolveRequest(query=args.name))
    salt = _salt()
    candidates = []
    for candidate in response.candidates:
        rendered = {
            "group": candidate.kind,
            "name": candidate.name,
            "email": candidate.email,
            "org": candidate.organization,
        }
        if args.masked:
            rendered.update(
                {
                    key: mask_value(value, salt)
                    for key, value in rendered.items()
                    if key != "group"
                }
            )
        candidates.append(rendered)
    query = mask_value(response.query, salt) if args.masked else response.query
    return _emit(
        {
            "wrapper": WRAPPER_VERSION,
            "command": "resolve",
            "status": "ok",
            "masked": args.masked,
            "query": query,
            "candidate_count": len(candidates),
            "candidates": candidates,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mail_wrapper.py")
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("list")
    command.add_argument("--limit", type=int, default=5)
    command.add_argument("--sync", action="store_true")
    command.add_argument("--masked", action="store_true")
    command.set_defaults(handler=cmd_list)

    command = subparsers.add_parser("get")
    command.add_argument("uid")
    command.add_argument("--body", action="store_true")
    command.add_argument("--masked", action="store_true")
    command.set_defaults(handler=cmd_get)

    command = subparsers.add_parser("classify")
    command.add_argument("--uid")
    command.add_argument("--subject")
    command.add_argument("--sender")
    command.add_argument("--masked", action="store_true")
    command.set_defaults(handler=cmd_classify)

    command = subparsers.add_parser("resolve")
    command.add_argument("--name", required=True)
    command.add_argument("--masked", action="store_true")
    command.set_defaults(handler=cmd_resolve)

    subparsers.add_parser("status").set_defaults(handler=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "classify" and not (args.uid or args.subject or args.sender):
        return _error("classify", "usage_error", "uid, subject, or sender is required")
    try:
        return int(args.handler(args))
    except site_mail_backend.BackendUnavailable:
        return _error(
            args.command,
            "backend_unavailable",
            "Configure an available backend with SITE_MAIL_BACKEND_CONFIG",
        )


if __name__ == "__main__":
    raise SystemExit(main())
