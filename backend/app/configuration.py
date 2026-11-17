import base64
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_authenticated_user
from app.database import get_db
from app.models import AuditLog, SystemSetting, User
from app.phone import DEFAULT_NETWORK_PREFIXES, normalize_kenyan_mobile


router = APIRouter(prefix="/api/settings", tags=["configuration"])


class BillingUpdate(BaseModel):
    cost_per_segment_kes: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=4)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    monthly_budget_kes: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    alert_threshold_percent: int | None = Field(default=None, ge=1, le=100)
    network_rates: dict[str, Decimal] | None = None


class GatewayUpdate(BaseModel):
    base_url: HttpUrl | None = None
    username: str | None = Field(default=None, max_length=120)
    api_key: str | None = Field(default=None, max_length=1024)
    default_sender_id: str | None = Field(default=None, min_length=1, max_length=11, pattern=r"^[A-Za-z0-9 ]+$")
    allowed_sender_ids: list[str] | None = None


class LimitsUpdate(BaseModel):
    send_rate_per_second: int | None = Field(default=None, ge=1, le=1000)
    max_segments: int | None = Field(default=None, ge=1, le=3)
    stale_queue_minutes: int | None = Field(default=None, ge=1, le=10080)
    retry_attempts: int | None = Field(default=None, ge=1, le=10)


class SafetyUpdate(BaseModel):
    max_per_recipient_hour: int | None = Field(default=None, ge=1, le=100)
    duplicate_window_minutes: int | None = Field(default=None, ge=1, le=1440)
    test_mode: bool | None = None
    fake_gateway: bool | None = None
    test_allowlist: list[str] | None = None


class QuietHoursUpdate(BaseModel):
    enabled: bool | None = None
    start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class RetentionUpdate(BaseModel):
    message_retention_days: int | None = Field(default=None, ge=1, le=3650)
    audit_log_retention_days: int | None = Field(default=None, ge=1, le=3650)


class MonitoringUpdate(BaseModel):
    service_a_silence_minutes: int | None = Field(default=None, ge=1, le=1440)
    error_rate_threshold_percent: int | None = Field(default=None, ge=1, le=100)
    low_credit_kes: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    slack_webhook_url: str | None = Field(default=None, max_length=1000)
    telegram_bot_token: str | None = Field(default=None, max_length=200)
    telegram_chat_id: str | None = Field(default=None, max_length=120)
    oncall_phone: str | None = Field(default=None, max_length=24)


class ConfigurationUpdate(BaseModel):
    billing: BillingUpdate | None = None
    gateway: GatewayUpdate | None = None
    limits: LimitsUpdate | None = None
    safety: SafetyUpdate | None = None
    quiet_hours: QuietHoursUpdate | None = None
    retention: RetentionUpdate | None = None
    monitoring: MonitoringUpdate | None = None
    network_prefixes: dict[str, list[str]] | None = None
    alert_emails: list[str] | None = None
    timezone: str | None = Field(default=None, max_length=64)


DEFAULTS: dict[str, Any] = {
    "billing": {"cost_per_segment_kes": "0.80", "currency": "KES", "monthly_budget_kes": "20000.00", "alert_threshold_percent": 80, "network_rates": {}},
    "gateway": {"base_url": None, "username": None, "encrypted_api_key": None, "default_sender_id": "UPENFLOW", "allowed_sender_ids": ["UPENFLOW"]},
    "limits": {"send_rate_per_second": 20, "max_segments": 3, "stale_queue_minutes": 60, "retry_attempts": 3},
    "safety": {"max_per_recipient_hour": 5, "duplicate_window_minutes": 10, "test_mode": False, "fake_gateway": False, "test_allowlist": []},
    "quiet_hours": {"enabled": False, "start": "21:00", "end": "07:00"},
    "retention": {"message_retention_days": 180, "audit_log_retention_days": 730},
    "monitoring": {
        "service_a_silence_minutes": 30,
        "error_rate_threshold_percent": 20,
        "low_credit_kes": "1000.00",
        "encrypted_slack_webhook_url": None,
        "encrypted_telegram_bot_token": None,
        "telegram_chat_id": None,
        "oncall_phone": None,
    },
    "network_prefixes": DEFAULT_NETWORK_PREFIXES,
    "alert_emails": [],
    "timezone": "Africa/Nairobi",
}


def require_super_admin(user: User = Depends(get_authenticated_user)) -> User:
    if user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin access required")
    return user


def cipher(request: Request) -> Fernet:
    secret = request.app.state.settings.secret_encryption_key or request.app.state.settings.otp_pepper
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def decrypt_secret(encrypted: str, secret: str) -> str:
    key = Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))
    return key.decrypt(encrypted.encode()).decode()


def public_configuration(data: dict, request: Request) -> dict:
    result = {key: value.copy() if isinstance(value, dict) else value for key, value in data.items()}
    gateway = result["gateway"]
    encrypted_key = gateway.pop("encrypted_api_key", None)
    gateway["api_key"] = "••••••••" if encrypted_key else None
    gateway["has_api_key"] = bool(encrypted_key)
    monitoring = result.setdefault("monitoring", {key: value for key, value in DEFAULTS["monitoring"].items()})
    encrypted_slack = monitoring.pop("encrypted_slack_webhook_url", None)
    encrypted_telegram = monitoring.pop("encrypted_telegram_bot_token", None)
    monitoring["slack_webhook_url"] = "••••••••" if encrypted_slack else None
    monitoring["has_slack_webhook"] = bool(encrypted_slack)
    monitoring["telegram_bot_token"] = "••••••••" if encrypted_telegram else None
    monitoring["has_telegram_bot_token"] = bool(encrypted_telegram)
    return result


def with_defaults(value: dict) -> dict:
    merged = {key: (item.copy() if isinstance(item, dict) else item) for key, item in DEFAULTS.items()}
    for key, item in value.items():
        if isinstance(item, dict) and isinstance(merged.get(key), dict):
            merged[key].update(item)
        else:
            merged[key] = item
    return merged


@router.get("")
def get_configuration(request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    record = db.scalar(select(SystemSetting).where(SystemSetting.key == "configuration"))
    return public_configuration(with_defaults(record.value) if record else DEFAULTS, request)


@router.patch("")
def update_configuration(payload: ConfigurationUpdate, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    record = db.scalar(select(SystemSetting).where(SystemSetting.key == "configuration"))
    before = with_defaults(record.value) if record else {key: value.copy() if isinstance(value, dict) else value for key, value in DEFAULTS.items()}
    after = {key: value.copy() if isinstance(value, dict) else value for key, value in before.items()}
    changes = payload.model_dump(exclude_unset=True, mode="json")
    for group in ("billing", "limits", "safety", "quiet_hours", "retention"):
        if changes.get(group):
            after[group].update(changes[group])
    if changes.get("quiet_hours"):
        start = after["quiet_hours"].get("start")
        end = after["quiet_hours"].get("end")
        if start and end and start == end:
            raise HTTPException(status_code=422, detail="Quiet hours start and end must differ")
    if changes.get("safety") and "test_allowlist" in changes["safety"]:
        normalized_numbers = [normalize_kenyan_mobile(number) for number in changes["safety"]["test_allowlist"]]
        if any(number is None for number in normalized_numbers):
            raise HTTPException(status_code=422, detail="Test allowlist accepts Kenyan mobile numbers only")
        after["safety"]["test_allowlist"] = normalized_numbers
    if changes.get("gateway"):
        gateway_changes = changes["gateway"].copy()
        api_key = gateway_changes.pop("api_key", None)
        if api_key:
            after["gateway"]["encrypted_api_key"] = cipher(request).encrypt(api_key.encode()).decode()
        after["gateway"].update(gateway_changes)
        allowed = after["gateway"].get("allowed_sender_ids") or []
        if any(not sender or len(sender) > 11 or not sender.isalnum() for sender in allowed):
            raise HTTPException(status_code=422, detail="Allowed Sender IDs must be alphanumeric and 11 characters or fewer")
        default_sender = after["gateway"].get("default_sender_id")
        if default_sender not in allowed:
            raise HTTPException(status_code=422, detail="Default Sender ID must be in the allowed list")
    if changes.get("monitoring"):
        monitoring_changes = changes["monitoring"].copy()
        slack_url = monitoring_changes.pop("slack_webhook_url", None)
        telegram_token = monitoring_changes.pop("telegram_bot_token", None)
        if slack_url:
            after["monitoring"]["encrypted_slack_webhook_url"] = cipher(request).encrypt(slack_url.encode()).decode()
        if telegram_token:
            after["monitoring"]["encrypted_telegram_bot_token"] = cipher(request).encrypt(telegram_token.encode()).decode()
        after["monitoring"].update(monitoring_changes)
    if changes.get("network_prefixes") is not None:
        for network, prefixes in changes["network_prefixes"].items():
            if not all(isinstance(prefix, str) and prefix.isdigit() and len(prefix) == 3 for prefix in prefixes):
                raise HTTPException(status_code=422, detail=f"Prefixes for {network} must be 3-digit numbers")
        after["network_prefixes"] = changes["network_prefixes"]
    if "alert_emails" in changes:
        after["alert_emails"] = changes["alert_emails"]
    if "timezone" in changes:
        after["timezone"] = changes["timezone"]
    now = datetime.now(timezone.utc)
    if record:
        record.value = after
        record.updated_by = admin.id
        record.updated_at = now
    else:
        db.add(SystemSetting(key="configuration", value=after, updated_by=admin.id, updated_at=now))
    old_public = public_configuration(before, request)
    new_public = public_configuration(after, request)
    db.add(AuditLog(
        actor_id=admin.id,
        action="configuration_updated",
        entity="setting",
        entity_id="configuration",
        before=old_public,
        after=new_public,
        ip_address=request.client.host if request.client else None,
        created_at=now,
    ))
    db.commit()
    return new_public