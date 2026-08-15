"""
Transactional email via Resend (HTTP API).

Enabled when RESEND_API_KEY is set. When unset, sends no-op and return False, so
callers fall back to surfacing the invite link in the UI. Sends never raise — an
email failure must not break the request that triggered it.
"""

import asyncio

from app.settings import settings
from app.logger import logger


def email_enabled() -> bool:
    return bool(settings.RESEND_API_KEY and settings.FROM_EMAIL)


def _send_via_resend(to_email: str, subject: str, html: str) -> None:
    # Lazy import so a missing dependency only breaks email, not server boot.
    import resend

    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send(
        {
            "from": f"{settings.FROM_NAME} <{settings.FROM_EMAIL}>",
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
    )


async def send_email(to_email: str, subject: str, html: str) -> bool:
    """Send an HTML email. Returns True on success, False if disabled/failed."""
    if not email_enabled():
        return False
    try:
        await asyncio.to_thread(_send_via_resend, to_email, subject, html)
        return True
    except Exception as e:
        logger.error(f"[email] send to {to_email} failed: {e}")
        return False


def _invitation_html(organization_name: str, role: str, invited_by: str, accept_url: str) -> str:
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:520px;margin:0 auto;padding:24px;color:#1a1a1a;">
  <div style="font-size:18px;font-weight:700;letter-spacing:-0.01em;margin-bottom:20px;color:#14140c;">SoldierIQ</div>
  <h1 style="font-size:20px;margin:0 0 8px;">You&apos;ve been invited to join {organization_name}</h1>
  <p style="font-size:14px;color:#555;margin:0 0 20px;">
    {invited_by} invited you to SoldierIQ as <strong>{role}</strong>.
  </p>
  <a href="{accept_url}" style="display:inline-block;background:#7a7249;color:#ffffff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;">Accept invitation</a>
  <p style="font-size:12px;color:#888;margin:24px 0 0;">Or paste this link into your browser:<br>
    <a href="{accept_url}" style="color:#7a7249;word-break:break-all;">{accept_url}</a>
  </p>
  <p style="font-size:12px;color:#aaa;margin:20px 0 0;">This invitation expires in 7 days. If you weren&apos;t expecting it, you can ignore this email.</p>
</div>"""


async def send_invitation_email(
    to_email: str, accept_url: str, organization_name: str, role: str, invited_by: str
) -> bool:
    subject = f"You're invited to join {organization_name} on SoldierIQ"
    html = _invitation_html(organization_name, role, invited_by, accept_url)
    return await send_email(to_email, subject, html)
