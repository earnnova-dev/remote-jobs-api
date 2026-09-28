"""Stdlib-only transactional email (SMTP) for password reset and other notices.

Configuration via environment (see server.py / .env):
  RJA_SMTP_HOST        SMTP server host (IP or hostname), e.g. "mail.example.com" or "10.0.0.5"
  RJA_SMTP_PORT        SMTP port, e.g. "587" (STARTTLS) or "465" (implicit TLS)
  RJA_SMTP_USER        SMTP username (optional; empty = anonymous / local relay)
  RJA_SMTP_PASS        SMTP password (optional)
  RJA_SMTP_FROM        From: address on outgoing mail (default: "Remote Jobs API <no-reply@...>")
  RJA_SMTP_FROM_NAME   Display name in the From address (default: "Remote Jobs API")
  RJA_SMTP_STARTTLS    "1" = STARTTLS on port 587 (default). "0" = plain.
  RJA_SMTP_SSL         "1" = implicit TLS on port 465 (takes precedence over STARTTLS).
  RJA_SMTP_TIMEOUT     Connection timeout in seconds (default: 15).

Stdlib only — no third-party deps. Fails closed: if mail cannot be sent, the
caller gets an exception (it decides whether to fall back to a safe log).
"""
from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from typing import Optional


class MailError(Exception):
    """Raised when a message cannot be delivered."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Mailer:
    def __init__(
        self,
        host: str = "",
        port: int = 587,
        user: str = "",
        password: str = "",
        from_addr: str = "",
        from_name: str = "Remote Jobs API",
        use_ssl: bool = False,
        use_starttls: bool = True,
        timeout: float = 15.0,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_name = from_name
        self.from_addr = from_addr or f"no-reply@{host}" if host else "no-reply@localhost"
        self.use_ssl = use_ssl
        self.use_starttls = use_starttls
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "Mailer":
        host = _env("RJA_SMTP_HOST")
        port = int(_env("RJA_SMTP_PORT", "587") or "587")
        user = _env("RJA_SMTP_USER")
        password = _env("RJA_SMTP_PASS")
        from_name = _env("RJA_SMTP_FROM_NAME", "Remote Jobs API")
        from_addr = _env("RJA_SMTP_FROM") or (f"no-reply@{host}" if host else "no-reply@localhost")
        use_ssl = _env("RJA_SMTP_SSL", "") == "1"
        # STARTTLS default is on unless explicitly disabled; implicit TLS wins.
        use_starttls = use_ssl or _env("RJA_SMTP_STARTTLS", "1") == "1"
        timeout = float(_env("RJA_SMTP_TIMEOUT", "15") or "15")
        return cls(
            host=host, port=port, user=user, password=password,
            from_addr=from_addr, from_name=from_name,
            use_ssl=use_ssl, use_starttls=use_starttls, timeout=timeout,
        )

    @property
    def configured(self) -> bool:
        return bool(self.host)

    def send(self, to_addr: str, subject: str, text_body: str, html_body: Optional[str] = None) -> None:
        """Send one message. Raises MailError on failure."""
        if not self.configured:
            raise MailError("SMTP not configured (RJA_SMTP_HOST is empty)")
        from email.mime.multipart import MIMEMultipart

        if html_body:
            mp = MIMEMultipart("alternative")
            mp.attach(MIMEText(text_body, "plain", "utf-8"))
            mp.attach(MIMEText(html_body, "html", "utf-8"))
            msg = mp
        else:
            msg = MIMEText(text_body, "plain", "utf-8")

        msg["Subject"] = subject
        msg["From"] = formataddr((self.from_name, self.from_addr))
        msg["To"] = to_addr
        msg["Message-ID"] = make_msgid(domain=self.from_addr.split("@")[-1] or "localhost")

        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            try:
                if self.use_starttls and not self.use_ssl:
                    server.starttls()
                if self.user:
                    server.login(self.user, self.password)
                server.sendmail(self.from_addr, [to_addr], msg.as_string())
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
        except smtplib.SMTPException as e:
            raise MailError(f"SMTP error: {e}") from e
        except OSError as e:
            raise MailError(f"SMTP network error: {e}") from e


def reset_email_html(subject: str, email: str, link: str, expires_minutes: int) -> str:
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#f6f8fa;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#0b0f14">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f8fa;padding:32px 0">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#ffffff;border:1px solid #e3e8ee;border-radius:12px;padding:32px">
        <tr><td style="font-size:18px;font-weight:700;margin-bottom:16px">Remote&nbsp;Jobs&nbsp;API</td></tr>
        <tr><td style="font-size:15px;line-height:1.6;color:#0b0f14;margin-bottom:20px">
          Hi {email},
        </td></tr>
        <tr><td style="font-size:15px;line-height:1.6;color:#0b0f14;margin-bottom:24px">
          You requested a password reset. Use the button below to choose a new password.
          This link expires in {expires_minutes} minutes. If you didn't request this,
          you can safely ignore this email.
        </td></tr>
        <tr><td style="margin-bottom:24px">
          <a href="{link}" style="display:inline-block;background:#4f46e5;color:#ffffff;text-decoration:none;font-size:15px;font-weight:600;padding:12px 22px;border-radius:8px">Reset my password</a>
        </td></tr>
        <tr><td style="font-size:13px;color:#6b7684;line-height:1.6;margin-bottom:24px">
          Or paste this into your browser:<br>
          <a href="{link}" style="color:#4f46e5;word-break:break-all">{link}</a>
        </td></tr>
        <tr><td style="font-size:13px;color:#6b7684">
          If the button doesn't work, contact support at
          <a href="mailto:earnnova@tten.no" style="color:#4f46e5">earnnova@tten.no</a>.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
