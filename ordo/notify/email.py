"""Email notifier using smtplib/email - standard library only."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .base import Notifier, NotifyError


class EmailNotifier(Notifier):
    name = "email"

    def __init__(self, host, port=587, username="", password="", sender="",
                 to=(), tls=True, timeout=20):
        if not host or not to:
            raise NotifyError(
                "email channel needs host and at least one recipient "
                "(set notify.email.host/to or ORDO_SMTP_HOST/ORDO_SMTP_TO)"
            )
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.sender = sender or username or "ordo@localhost"
        self.recipients = list(to)
        self.tls = bool(tls)
        self.timeout = timeout

    def send(self, message):
        email = EmailMessage()
        email["Subject"] = message.subject
        email["From"] = self.sender
        email["To"] = ", ".join(self.recipients)
        email.set_content(message.as_text())
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
                smtp.ehlo()
                if self.tls:
                    smtp.starttls()
                    smtp.ehlo()
                if self.username:
                    smtp.login(self.username, self.password)
                smtp.send_message(email)
        except Exception as exc:  # noqa: BLE001
            raise NotifyError("email send failed: %s" % exc)
        return []
