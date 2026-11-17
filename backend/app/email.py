import smtplib
from email.message import EmailMessage

from app.config import Settings


def send_otp_email(settings: Settings, recipient: str, code: str) -> None:
    send_account_email(
        settings,
        recipient,
        "Your Upenflow Notify verification code",
        f"Your verification code is {code}. It expires in 5 minutes.",
    )


def send_account_email(settings: Settings, recipient: str, subject: str, content: str) -> None:
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST must be configured to send login codes")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message.set_content(content)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(message)