import logging

import httpx

from app.config import Settings
from app.configuration import decrypt_secret
from app.email import send_account_email

logger = logging.getLogger("upenflow.alerts")


def secret_key(settings: Settings) -> str:
    return settings.secret_encryption_key or settings.otp_pepper


def send_alert(settings: Settings, configuration: dict, subject: str, message: str) -> None:
    for recipient in configuration.get("alert_emails", []):
        try:
            send_account_email(settings, recipient, subject, message)
        except Exception:
            logger.warning("alert_email_failed", extra={"fields": {"subject": subject}})

    monitoring = configuration.get("monitoring", {})
    encrypted_slack = monitoring.get("encrypted_slack_webhook_url")
    if encrypted_slack:
        try:
            webhook_url = decrypt_secret(encrypted_slack, secret_key(settings))
            httpx.post(webhook_url, json={"text": f"*{subject}*\n{message}"}, timeout=10.0)
        except Exception:
            logger.warning("alert_slack_failed", extra={"fields": {"subject": subject}})

    encrypted_telegram = monitoring.get("encrypted_telegram_bot_token")
    chat_id = monitoring.get("telegram_chat_id")
    if encrypted_telegram and chat_id:
        try:
            bot_token = decrypt_secret(encrypted_telegram, secret_key(settings))
            httpx.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": f"{subject}\n{message}"},
                timeout=10.0,
            )
        except Exception:
            logger.warning("alert_telegram_failed", extra={"fields": {"subject": subject}})

    oncall_phone = monitoring.get("oncall_phone")
    gateway = configuration.get("gateway", {})
    if oncall_phone and gateway.get("base_url") and gateway.get("encrypted_api_key") and gateway.get("encrypted_client_id") and gateway.get("encrypted_access_key"):
        try:
            from app.service_b import ServiceBAdapter

            key = secret_key(settings)
            api_key = decrypt_secret(gateway["encrypted_api_key"], key)
            client_id = decrypt_secret(gateway["encrypted_client_id"], key)
            access_key = decrypt_secret(gateway["encrypted_access_key"], key)
            adapter = ServiceBAdapter(gateway["base_url"], api_key, client_id, access_key)
            sender_id = gateway.get("default_sender_id", "UPENFLOW")
            adapter.send(sender_id, oncall_phone, f"{subject}: {message}"[:160], f"alert-{subject}")
        except Exception:
            logger.warning("alert_sms_failed", extra={"fields": {"subject": subject}})
