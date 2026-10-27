from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings


async def send_email(to_email: str, subject: str, text: str) -> None:
    if not settings.emails_enabled:
        return
    if not settings.smtp_username or not settings.smtp_password:
        raise RuntimeError("Email delivery is enabled but SMTP credentials are incomplete")

    message = EmailMessage()
    message["From"] = settings.smtp_from_email or settings.smtp_username
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(text)
    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        start_tls=True,
        username=settings.smtp_username,
        password=settings.smtp_password,
    )


async def send_verification_email(email: str, token: str) -> None:
    link = f"{settings.frontend_url}/verify-email?token={token}"
    await send_email(email, "Verify your email", f"Verify your account:\n\n{link}\n")


async def send_reset_email(email: str, token: str) -> None:
    link = f"{settings.frontend_url}/reset-password?token={token}"
    await send_email(email, "Reset your password", f"Reset your password:\n\n{link}\n")


async def send_invitation_email(email: str, organization: str, token: str) -> None:
    link = f"{settings.frontend_url}/accept-invitation?token={token}"
    await send_email(
        email,
        f"Invitation to {organization}",
        f"You have been invited to {organization}:\n\n{link}\n",
    )
