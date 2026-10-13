"""
Email service — three delivery options (see EMAIL_PROVIDER in config.py):

  smtp    → Python smtplib with Gmail SMTP + STARTTLS (port 587).
            NOTE: many free hosts (e.g. Render free tier) block outbound SMTP ports.
  brevo   → Brevo transactional email HTTPS API (port 443) — works on free hosts.
            Free plan: 300 emails/day. The "from" address must be a verified sender in Brevo.
  console → nothing is sent; the code is written to the server log (prototype/demo only).

Gmail setup:
  1. Enable 2-Step Verification on your Google account.
  2. Go to Google Account → Security → App Passwords.
  3. Create an App Password (select "Mail" + "Other device").
  4. Use that 16-char password as SMTP_PASSWORD in your .env
     (NOT your normal Gmail login password).
"""
import json
import smtplib
import logging
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)


# ── HTML email template ──────────────────────────────────────────────────────

def _build_mfa_email(recipient_name: str, otp_code: str, expire_minutes: int) -> tuple[str, str]:
    """Returns (subject, html_body)"""
    subject = "Your Meridian Capital Sign-In Verification Code"

    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#0B1628;font-family:'Helvetica Neue',Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0B1628;padding:40px 0">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0"
             style="background:#0F1E35;border-radius:14px;border:1px solid rgba(201,168,76,0.2);overflow:hidden">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#8B6F2E,#C9A84C);padding:28px 40px;text-align:center">
            <span style="font-size:22px;font-weight:700;color:#0B1628;letter-spacing:0.06em">
              MERIDIAN CAPITAL
            </span><br>
            <span style="font-size:11px;color:#0B1628;opacity:0.75;letter-spacing:0.14em;text-transform:uppercase">
              Investor Portal
            </span>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:36px 40px">
            <p style="color:#D4CBB5;font-size:15px;margin:0 0 8px">
              Hello {recipient_name},
            </p>
            <p style="color:#7A8EA8;font-size:14px;line-height:1.6;margin:0 0 28px">
              Use the verification code below to complete your sign-in.
              This code expires in <strong style="color:#C9A84C">{expire_minutes} minutes</strong>.
            </p>

            <!-- OTP Box -->
            <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px">
              <tr>
                <td align="center"
                    style="background:#162B45;border:1px solid rgba(201,168,76,0.25);
                           border-radius:10px;padding:24px 0">
                  <span style="font-size:40px;font-weight:700;letter-spacing:12px;color:#C9A84C;
                               font-family:'Courier New',monospace">
                    {otp_code}
                  </span>
                </td>
              </tr>
            </table>

            <p style="color:#7A8EA8;font-size:13px;line-height:1.6;margin:0 0 6px">
              If you did not attempt to sign in, please contact Investor Relations immediately
              at <a href="mailto:ir@meridiancapital.com"
                    style="color:#C9A84C;text-decoration:none">ir@meridiancapital.com</a>.
            </p>
            <p style="color:#4A5A6A;font-size:12px;margin:0">
              Do not share this code with anyone, including Meridian Capital staff.
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="border-top:1px solid rgba(201,168,76,0.1);padding:20px 40px;text-align:center">
            <p style="color:#4A5A6A;font-size:11px;margin:0">
              © {datetime.now().year} Meridian Capital Management LLC &nbsp;·&nbsp;
              Confidential &amp; Privileged
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    return subject, html


def _build_plain_mfa(recipient_name: str, otp_code: str, expire_minutes: int) -> str:
    return (
        f"Hello {recipient_name},\n\n"
        f"Your Meridian Capital sign-in verification code is:\n\n"
        f"  {otp_code}\n\n"
        f"This code expires in {expire_minutes} minutes.\n\n"
        f"If you did not attempt to sign in, contact ir@meridiancapital.com immediately.\n\n"
        f"— Meridian Capital Investor Relations"
    )


# ── Send function ────────────────────────────────────────────────────────────

def send_mfa_email(recipient_email: str, recipient_name: str, otp_code: str) -> bool:
    """
    Sends the MFA OTP using the configured provider.
    Returns True on success, False on failure. Never raises.
    """
    subject, html_body = _build_mfa_email(recipient_name, otp_code, settings.OTP_EXPIRE_MINUTES)
    plain_body = _build_plain_mfa(recipient_name, otp_code, settings.OTP_EXPIRE_MINUTES)
    provider = settings.email_provider

    if provider == "brevo":
        return _send_brevo(recipient_email, recipient_name, subject, html_body, plain_body)
    if provider == "smtp":
        return _send_smtp(recipient_email, subject, html_body, plain_body)

    # console
    logger.warning("EMAIL_PROVIDER=console — OTP for %s is %s (not emailed)", recipient_email, otp_code)
    return False


def _send_brevo(recipient_email: str, recipient_name: str, subject: str,
                html_body: str, plain_body: str) -> bool:
    if not settings.BREVO_API_KEY or not settings.email_from:
        logger.error("Brevo selected but BREVO_API_KEY or EMAIL_FROM_ADDRESS is missing")
        return False
    payload = {
        "sender": {"name": settings.EMAIL_FROM_NAME, "email": settings.email_from},
        "to": [{"email": recipient_email, "name": recipient_name}],
        "subject": subject,
        "htmlContent": html_body,
        "textContent": plain_body,
    }
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode(),
        headers={
            "api-key": settings.BREVO_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = 200 <= resp.status < 300
        if ok:
            logger.info(f"MFA email sent via Brevo → {recipient_email}")
        return ok
    except urllib.error.HTTPError as exc:
        logger.error(f"Brevo API error {exc.code}: {exc.read()[:300]!r}")
        return False
    except Exception as exc:
        logger.error(f"Brevo send failed for {recipient_email}: {exc}")
        return False


def _send_smtp(recipient_email: str, subject: str, html_body: str, plain_body: str) -> bool:
    """Gmail SMTP (STARTTLS on port 587)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = formataddr((settings.EMAIL_FROM_NAME, settings.email_from))
    msg["To"]      = recipient_email
    msg["X-Priority"] = "1"  # Mark as high priority

    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.email_from, [recipient_email], msg.as_string())
        logger.info(f"MFA email sent → {recipient_email}")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP authentication failed — check SMTP_USER and SMTP_PASSWORD (use Gmail App Password)")
        return False
    except smtplib.SMTPRecipientsRefused:
        logger.error(f"Recipient refused: {recipient_email}")
        return False
    except Exception as exc:
        logger.error(f"Failed to send MFA email to {recipient_email}: {exc}")
        return False
