import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.configuration import decrypt_secret
from app.database import build_engine, build_session_factory, get_db
from app.models import AuditLog, BlocklistEntry, InboundMessage, MappingRule, MappingRuleVersion, SystemSetting
from app.phone import DEFAULT_NETWORK_PREFIXES, detect_network, normalize_kenyan_mobile
from app.ratelimit import rate_limit_service_a
from app.rule_matching import match_rule, render_template, sms_segments, values_for
from app.rules import require_rule_editor
from app.service_b import ServiceBAdapter, ServiceBError

router = APIRouter(tags=["inbound"])


class ServiceAMessage(BaseModel):
    message_id: str = Field(min_length=1, max_length=255)
    recipient: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=10000)
    order_ref: str | None = Field(default=None, max_length=255)
    received_at: datetime | None = None


class ManualSendRequest(BaseModel):
    recipient: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=1600)
    sender_id: str | None = Field(default=None, max_length=11, pattern=r"^[A-Za-z0-9 ]*$")
    order_ref: str | None = Field(default=None, max_length=255)


def within_time_window(current: str, start: str, end: str) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def load_configuration_value(db: Session) -> dict | None:
    record = db.scalar(select(SystemSetting).where(SystemSetting.key == "configuration"))
    return record.value if record else None


@router.post("/api/messages/manual-send", status_code=status.HTTP_202_ACCEPTED)
def manual_send(
    payload: ManualSendRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user=Depends(require_rule_editor),
):
    """Send an outbound SMS directly, bypassing rule matching — a stand-in for Service A
    while it isn't wired up yet. Goes through the same delivery pipeline (throttle,
    duplicate guard, blocklist, quiet hours, global switch, cost tracking) as any other
    message, so it shows up in Notifications/Dashboard exactly like a normal send."""
    recipient = normalize_kenyan_mobile(payload.recipient)
    if not recipient:
        raise HTTPException(status_code=422, detail="Only Kenyan mobile numbers are accepted")
    configuration = load_configuration_value(db) or {}
    gateway = configuration.get("gateway", {})
    sender_id = (payload.sender_id or gateway.get("default_sender_id") or "").upper()
    if sender_id not in (gateway.get("allowed_sender_ids") or []):
        raise HTTPException(status_code=422, detail="Sender ID is not in the allowed list")
    prefix_table = configuration.get("network_prefixes") or DEFAULT_NETWORK_PREFIXES
    now = datetime.now(timezone.utc)
    message = InboundMessage(
        source_message_id=f"manual-{uuid.uuid4()}",
        recipient=recipient,
        text=payload.text,
        order_ref=payload.order_ref,
        raw_payload={"manual_send": True, "created_by_user_id": user.id},
        received_at=now,
        status="Queued",
        sender_id=sender_id,
        rendered_text=payload.text,
        network=detect_network(recipient, prefix_table),
    )
    db.add(message)
    db.flush()
    db.add(
        AuditLog(
            actor_id=user.id,
            action="message_manual_send",
            entity="message",
            entity_id=str(message.id),
            before=None,
            after={"recipient": recipient, "sender_id": sender_id, "text": payload.text[:200]},
            ip_address=request.client.host if request.client else None,
            created_at=now,
        )
    )
    db.commit()
    enqueue_delivery(request, background_tasks, message.id)
    return {"accepted": True, "message_id": message.id}


def process_inbound_message(session_factory, message_id: int, runtime_settings: Settings | None = None) -> None:
    with session_factory() as db:
        message = db.get(InboundMessage, message_id)
        if not message or message.status != "Received":
            return
        rules = db.scalars(
            select(MappingRule)
            .where(MappingRule.deleted_at.is_(None))
            .order_by(MappingRule.priority, MappingRule.id)
        ).all()
        for rule in rules:
            groups = match_rule(rule, message.text)
            if groups is None:
                continue
            version = db.scalar(
                select(MappingRuleVersion).where(
                    MappingRuleVersion.rule_id == rule.id,
                    MappingRuleVersion.version == rule.version,
                )
            )
            message.rule_id = rule.id
            message.rule_version_id = version.id if version else None
            message.sender_id = rule.sender_id
            message.rendered_text = render_template(
                rule.outbound_template,
                values_for(message.text, message.recipient, message.order_ref, groups),
            )
            if not rule.is_enabled:
                message.status = "Suppressed"
            else:
                sending = db.scalar(select(SystemSetting).where(SystemSetting.key == "sending"))
                switch_state = sending.value["state"] if sending else "on"
                message.status = "Skipped" if switch_state == "stopped" else "Queued"
                if switch_state == "stopped":
                    message.status_reason = "Global sending is stopped"
            db.commit()
            if message.status == "Queued":
                deliver_queued_message(session_factory, message.id, runtime_settings)
            return
        message.status = "Unmapped"
        db.commit()


def process_queued_inbound_message(database_url: str, message_id: int) -> None:
    from app.config import get_settings

    engine = build_engine(database_url)
    try:
        process_inbound_message(build_session_factory(engine), message_id, get_settings())
    finally:
        engine.dispose()


def deliver_queued_message_job(database_url: str, message_id: int) -> None:
    from app.config import get_settings

    engine = build_engine(database_url)
    try:
        deliver_queued_message(build_session_factory(engine), message_id, get_settings())
    finally:
        engine.dispose()


def enqueue_delivery(request: Request, background_tasks: BackgroundTasks, message_id: int) -> None:
    settings: Settings = request.app.state.settings
    if not settings.redis_url:
        background_tasks.add_task(deliver_queued_message, request.app.state.session_factory, message_id, settings)
        return
    try:
        from redis import Redis
        from rq import Queue

        Queue("notifications", connection=Redis.from_url(settings.redis_url)).enqueue(
            deliver_queued_message_job,
            settings.database_url,
            message_id,
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail="Outbound processing queue unavailable") from error


class _DeliveryHalted(Exception):
    """Raised by a guard below to stop the pipeline and record a terminal status."""

    def __init__(self, status: str, status_reason: str | None = None):
        super().__init__(status_reason or status)
        self.status = status
        self.status_reason = status_reason


def _decrypt_gateway_credentials(gateway: dict, settings: Settings) -> tuple[str, str, str]:
    secret_key = settings.secret_encryption_key or settings.otp_pepper
    try:
        return (
            decrypt_secret(gateway["encrypted_api_key"], secret_key),
            decrypt_secret(gateway["encrypted_client_id"], secret_key),
            decrypt_secret(gateway["encrypted_access_key"], secret_key),
        )
    except Exception as error:
        raise _DeliveryHalted("Failed", "Gateway credentials could not be decrypted") from error


def _check_rule_still_enabled(db: Session, message: InboundMessage) -> None:
    rule = db.get(MappingRule, message.rule_id) if message.rule_id else None
    if message.rule_id and (not rule or not rule.is_enabled):
        raise _DeliveryHalted("Suppressed", "Mapping rule disabled before send")


def _check_global_switch(db: Session) -> None:
    switch = db.scalar(select(SystemSetting).where(SystemSetting.key == "sending"))
    state = switch.value["state"] if switch else "on"
    if state != "on":
        raise _DeliveryHalted(
            "Skipped" if state == "stopped" else "Queued",
            "Global sending is stopped" if state == "stopped" else "Global sending is paused",
        )


def _check_quiet_hours(configuration) -> None:
    quiet_hours = configuration.value.get("quiet_hours", {}) if configuration else {}
    if not quiet_hours.get("enabled"):
        return
    from zoneinfo import ZoneInfo

    tz_name = configuration.value.get("timezone", "Africa/Nairobi") if configuration else "Africa/Nairobi"
    now_local = datetime.now(ZoneInfo(tz_name))
    if within_time_window(now_local.strftime("%H:%M"), quiet_hours.get("start", "21:00"), quiet_hours.get("end", "07:00")):
        raise _DeliveryHalted("Queued", "Queued: quiet hours active")


def _normalize_and_tag_network(message: InboundMessage, configuration) -> str:
    recipient = normalize_kenyan_mobile(message.recipient)
    if not recipient:
        raise _DeliveryHalted("Invalid recipient", "Only Kenyan mobile numbers are accepted")
    message.recipient = recipient
    if not message.network:
        message.network = detect_network(recipient, (configuration.value.get("network_prefixes") if configuration else None) or DEFAULT_NETWORK_PREFIXES)
    return recipient


def _check_segment_limit(message: InboundMessage, limits: dict) -> tuple[int, str]:
    segments, encoding, _ = sms_segments(message.rendered_text or "")
    max_segments = int(limits.get("max_segments", 3))
    if segments > max_segments:
        raise _DeliveryHalted("Blocked", f"Message exceeds the {max_segments}-segment limit")
    return segments, encoding


def _check_sender_id_allowed(message: InboundMessage, gateway: dict) -> str:
    sender_id = message.sender_id or gateway.get("default_sender_id")
    if sender_id not in gateway.get("allowed_sender_ids", []):
        raise _DeliveryHalted("Blocked", "Sender ID is not in the allowed list")
    return sender_id


def _check_not_blocklisted(db: Session, recipient: str) -> None:
    blocked = db.scalar(
        select(BlocklistEntry).where(BlocklistEntry.phone_number == recipient, BlocklistEntry.removed_at.is_(None))
    )
    if blocked:
        raise _DeliveryHalted("Blocked", "Recipient is on the blocklist")


def _check_not_duplicate(db: Session, message: InboundMessage, recipient: str, safety: dict) -> None:
    duplicate_cutoff = message.received_at - timedelta(minutes=int(safety.get("duplicate_window_minutes", 10)))
    duplicate = db.scalar(
        select(InboundMessage.id).where(
            InboundMessage.id != message.id,
            InboundMessage.recipient == recipient,
            InboundMessage.rendered_text == message.rendered_text,
            InboundMessage.received_at >= duplicate_cutoff,
        ).limit(1)
    )
    if duplicate:
        raise _DeliveryHalted("Blocked", "Duplicate message to this recipient")


def _check_recipient_throttle(db: Session, message: InboundMessage, recipient: str, safety: dict) -> None:
    throttle_cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    sent_count = db.scalar(
        select(func.count()).select_from(InboundMessage).where(
            InboundMessage.id != message.id,
            InboundMessage.recipient == recipient,
            InboundMessage.status.in_(["Sent", "Delivered"]),
            InboundMessage.sent_at >= throttle_cutoff,
        )
    ) or 0
    if sent_count >= int(safety.get("max_per_recipient_hour", 5)):
        raise _DeliveryHalted("Throttled", "Recipient hourly message limit reached")


def _check_test_mode_allowlist(recipient: str, safety: dict) -> None:
    if safety.get("test_mode") and recipient not in safety.get("test_allowlist", []):
        raise _DeliveryHalted("Blocked", "Recipient is not on the test-mode allowlist")


def _resolve_billing_rate(message: InboundMessage, billing: dict) -> Decimal:
    network_rates = billing.get("network_rates", {})
    rate_value = network_rates.get(message.network) if message.network else None
    return Decimal(str(rate_value if rate_value is not None else billing.get("cost_per_segment_kes", "0.80")))


def deliver_queued_message(session_factory, message_id: int, runtime_settings: Settings | None = None) -> None:
    from app.config import get_settings

    settings = runtime_settings or get_settings()
    with session_factory() as db:
        message = db.get(InboundMessage, message_id)
        if not message or message.status != "Queued":
            return
        configuration = db.scalar(select(SystemSetting).where(SystemSetting.key == "configuration"))
        gateway = configuration.value.get("gateway", {}) if configuration else {}
        if not gateway.get("base_url") or not gateway.get("encrypted_api_key") or not gateway.get("encrypted_client_id") or not gateway.get("encrypted_access_key"):
            return

        try:
            api_key, client_id, access_key = _decrypt_gateway_credentials(gateway, settings)
            _check_rule_still_enabled(db, message)
            _check_global_switch(db)
            _check_quiet_hours(configuration)
            recipient = _normalize_and_tag_network(message, configuration)
            limits = configuration.value.get("limits", {})
            segments, encoding = _check_segment_limit(message, limits)
            sender_id = _check_sender_id_allowed(message, gateway)
            safety = configuration.value.get("safety", {})
            _check_not_blocklisted(db, recipient)
            _check_not_duplicate(db, message, recipient, safety)
            _check_recipient_throttle(db, message, recipient, safety)
            _check_test_mode_allowlist(recipient, safety)
        except _DeliveryHalted as halt:
            message.status = halt.status
            message.status_reason = halt.status_reason
            db.commit()
            return

        billing = configuration.value.get("billing", {})
        rate = _resolve_billing_rate(message, billing)
        retries = int(limits.get("retry_attempts", 3))
        if safety.get("test_mode") and safety.get("fake_gateway"):
            message.status = "Sent"
            message.provider_message_id = f"test-{message.source_message_id}"
            message.sent_at = datetime.now(timezone.utc)
            message.segments = segments
            message.rate_per_segment_kes = rate
            message.cost_kes = 0
            db.commit()
            return
        message.status = "Sending"
        db.commit()

    _send_with_retries(session_factory, message_id, gateway, api_key, client_id, access_key, sender_id, recipient, encoding, segments, rate, retries)


def _send_with_retries(
    session_factory, message_id: int, gateway: dict, api_key: str, client_id: str, access_key: str,
    sender_id: str, recipient: str, encoding: str, segments: int, rate: Decimal, retries: int,
) -> None:
    adapter = ServiceBAdapter(gateway["base_url"], api_key, client_id, access_key)
    for attempt in range(retries):
        with session_factory() as db:
            message = db.get(InboundMessage, message_id)
            rule = db.get(MappingRule, message.rule_id) if message and message.rule_id else None
            switch = db.scalar(select(SystemSetting).where(SystemSetting.key == "sending"))
            state = switch.value["state"] if switch else "on"
            if not message or message.status != "Sending":
                return
            if message.rule_id and (not rule or not rule.is_enabled):
                message.status = "Suppressed"
                message.status_reason = "Mapping rule disabled before send"
                db.commit()
                return
            if state != "on":
                message.status = "Skipped" if state == "stopped" else "Queued"
                message.status_reason = "Global sending is stopped" if state == "stopped" else "Global sending is paused"
                db.commit()
                return
            message.attempts += 1
            db.commit()
        try:
            provider_id = adapter.send(sender_id, recipient, message.rendered_text or "", message.source_message_id, is_unicode=(encoding == "Unicode"))
        except ServiceBError as error:
            with session_factory() as db:
                message = db.get(InboundMessage, message_id)
                if not error.retryable or attempt + 1 >= retries:
                    message.status = "Failed"
                    message.error = str(error)
                    message.cost_kes = 0
                    db.commit()
                    return
            time.sleep(min(30 * (2**attempt), 600))
            continue
        with session_factory() as db:
            message = db.get(InboundMessage, message_id)
            message.provider_message_id = provider_id
            message.status = "Sent"
            message.sent_at = datetime.now(timezone.utc)
            message.segments = segments
            message.rate_per_segment_kes = rate
            message.cost_kes = rate * segments
            message.error = None
            db.commit()
        return


def enqueue_inbound(request: Request, background_tasks: BackgroundTasks, message_id: int) -> None:
    settings: Settings = request.app.state.settings
    if not settings.redis_url:
        background_tasks.add_task(process_inbound_message, request.app.state.session_factory, message_id, settings)
        return
    try:
        from redis import Redis
        from rq import Queue

        Queue("notifications", connection=Redis.from_url(settings.redis_url)).enqueue(
            process_queued_inbound_message,
            settings.database_url,
            message_id,
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail="Inbound processing queue unavailable") from error


@router.post("/api/inbound/service-a", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(rate_limit_service_a)])
async def receive_service_a(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    service_key: str | None = Header(default=None, alias="X-Service-A-Key"),
    timestamp: str | None = Header(default=None, alias="X-Service-A-Timestamp"),
    signature: str | None = Header(default=None, alias="X-Service-A-Signature"),
):
    settings: Settings = request.app.state.settings
    if not settings.service_a_api_key or not settings.service_a_hmac_secret:
        raise HTTPException(status_code=503, detail="Inbound authentication is not configured")
    if not service_key or not hmac.compare_digest(service_key, settings.service_a_api_key):
        raise HTTPException(status_code=401, detail="Invalid webhook credentials")
    try:
        timestamp_value = int(timestamp or "")
    except ValueError as error:
        raise HTTPException(status_code=401, detail="Invalid webhook timestamp") from error
    if abs(time.time() - timestamp_value) > 300:
        raise HTTPException(status_code=401, detail="Webhook timestamp expired")
    raw_body = await request.body()
    expected = hmac.new(
        settings.service_a_hmac_secret.encode(),
        timestamp.encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    supplied = (signature or "").removeprefix("sha256=")
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = ServiceAMessage.model_validate_json(raw_body)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Invalid message payload") from error

    data = payload.model_dump()
    data["received_at"] = payload.received_at or datetime.now(timezone.utc)
    normalized_recipient = normalize_kenyan_mobile(payload.recipient)
    configuration = load_configuration_value(db)
    prefix_table = (configuration.get("network_prefixes") if configuration else None) or DEFAULT_NETWORK_PREFIXES
    message = InboundMessage(
        source_message_id=payload.message_id,
        recipient=normalized_recipient or payload.recipient,
        text=payload.text,
        order_ref=payload.order_ref,
        raw_payload=json.loads(raw_body),
        received_at=data["received_at"],
        status="Received" if normalized_recipient else "Invalid recipient",
        status_reason=None if normalized_recipient else "Only Kenyan mobile numbers are accepted",
        network=detect_network(normalized_recipient, prefix_table) if normalized_recipient else None,
    )
    db.add(message)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(InboundMessage).where(InboundMessage.source_message_id == payload.message_id)
        )
        if existing and existing.status == "Received":
            enqueue_inbound(request, background_tasks, existing.id)
        return {"accepted": True, "duplicate": True}
    db.refresh(message)
    if message.status == "Received":
        enqueue_inbound(request, background_tasks, message.id)
    return {"accepted": True, "duplicate": False}
