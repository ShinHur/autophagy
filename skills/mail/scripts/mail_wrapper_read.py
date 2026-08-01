from __future__ import annotations

import hashlib

import site_mail_backend


def mask_value(value: str, salt: str = "") -> str:
    digest = hashlib.sha256((salt + value).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def render_summary(
    mail: site_mail_backend.MailSummary,
    *,
    masked: bool,
    salt: str,
) -> dict[str, str]:
    subject = mask_value(mail.subject, salt) if masked else mail.subject
    sender = mask_value(mail.sender, salt) if masked else mail.sender
    return {
        "uid": mail.message_id,
        "folder": mail.folder,
        "date": mail.received_at,
        "subject": subject,
        "sender": sender,
    }


def render_detail(
    mail: site_mail_backend.MailDetail,
    *,
    masked: bool,
    salt: str,
    include_body: bool,
) -> dict[str, str | int | None]:
    rendered: dict[str, str | int | None] = render_summary(
        site_mail_backend.MailSummary(
            mail.message_id,
            mail.folder,
            mail.subject,
            mail.sender,
            mail.received_at,
        ),
        masked=masked,
        salt=salt,
    )
    if not include_body:
        return rendered
    if masked and mail.body is not None:
        encoded = mail.body.encode("utf-8")
        rendered["body_sha256"] = hashlib.sha256(encoded).hexdigest()
        rendered["body_bytes"] = len(encoded)
    elif not masked:
        rendered["body"] = mail.body
    return rendered
