from __future__ import annotations

import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def send_markdown_email(
    *,
    subject: str,
    markdown_body: str,
    smtp_settings: dict[str, Any],
) -> bool:
    """Legacy function for backward compatibility. Now sends HTML email."""
    html_file = smtp_settings.get("html_file")
    if html_file and Path(html_file).exists():
        return send_html_email(
            subject=subject,
            html_file=html_file,
            smtp_settings=smtp_settings,
        )
    # Fallback: send markdown as plaintext if HTML file not available
    return send_html_email(
        subject=subject,
        html_file=None,
        smtp_settings=smtp_settings,
    )


def send_html_email(
    *,
    subject: str,
    html_file: str | Path | None,
    smtp_settings: dict[str, Any],
) -> bool:
    """Send newsletter as HTML email with plaintext fallback."""
    sender = smtp_settings.get("sender")
    recipient = smtp_settings.get("recipient")
    host = smtp_settings.get("host")
    username = smtp_settings.get("username")
    password = smtp_settings.get("password")
    port = int(smtp_settings.get("port", 587))
    use_tls = _as_bool(smtp_settings.get("use_tls", True))

    missing_fields = [
        field_name
        for field_name, value in {
            "NEWSLETTER_EMAIL_FROM": sender,
            "NEWSLETTER_EMAIL_TO": recipient,
            "SMTP_HOST": host,
            "SMTP_USERNAME": username,
            "SMTP_PASSWORD": password,
        }.items()
        if not value
    ]

    if missing_fields:
        logger.warning("Skipping email send because config is incomplete: %s", ", ".join(missing_fields))
        return False

    # Read HTML from file if provided and exists
    html_body = ""
    html_file_path = None
    if html_file:
        html_path = Path(html_file)
        if html_path.exists():
            html_body = html_path.read_text(encoding="utf-8")
            html_file_path = html_path
        else:
            logger.warning("HTML file not found: %s", html_file)

    # Create multipart message with plaintext fallback
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient

    # Plaintext fallback
    text_part = MIMEText("Your daily newsletter is ready. View in an HTML-compatible email client.", "plain")
    message.attach(text_part)

    # HTML body (preferred)
    if html_body:
        html_part = MIMEText(html_body, "html")
        message.attach(html_part)

    # Attach HTML file for easy mobile viewing
    if html_file_path and html_file_path.exists():
        with open(html_file_path, "rb") as attachment:
            file_content = attachment.read()
            file_attachment = MIMEApplication(file_content, Name=html_file_path.name)
            file_attachment["Content-Disposition"] = f"attachment; filename={html_file_path.name}"
            message.attach(file_attachment)

    with smtplib.SMTP(host=host, port=port, timeout=30) as smtp:
        if use_tls:
            smtp.starttls()
        smtp.login(username, password)
        smtp.send_message(message)

    logger.info("Newsletter email sent to %s", recipient)
    return True


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {"1", "true", "yes", "on"}
