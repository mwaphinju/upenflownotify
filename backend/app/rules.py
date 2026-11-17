import hashlib
import hmac
import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_authenticated_user
from app.config import Settings
from app.configuration import decrypt_secret
from app.database import build_engine, build_session_factory, get_db
from app.models import AuditLog, BlocklistEntry, InboundMessage, MappingRule, MappingRuleVersion, SystemSetting, User
from app.phone import DEFAULT_NETWORK_PREFIXES, detect_network, normalize_kenyan_mobile
from app.service_b import ServiceBAdapter, ServiceBError


router = APIRouter(tags=["mapping rules", "inbound"])
BUILTIN_PLACEHOLDERS = {"recipient", "order_ref", "original_text", "date"}
PLACEHOLDER_PATTERN = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")
GSM_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ "
    "!\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿"
    "abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM_EXTENDED = set("^{}\\[~]|€")


class RuleFields(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    priority: int = Field(ge=0)
    match_type: Literal["contains", "starts_with", "exact", "regex"]
    match_value: str = Field(min_length=1, max_length=1000)
    case_sensitive: bool = False
    sender_id: str = Field(min_length=1, max_length=11, pattern=r"^[A-Za-z0-9 ]+$")
    outbound_template: str = Field(min_length=1, max_length=1600)
    is_enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    priority: int | None = Field(default=None, ge=0)
    match_type: Literal["contains", "starts_with", "exact", "regex"] | None = None
    match_value: str | None = Field(default=None, min_length=1, max_length=1000)
    case_sensitive: bool | None = None
    sender_id: str | None = Field(default=None, min_length=1, max_length=11, pattern=r"^[A-Za-z0-9 ]+$")
    outbound_template: str | None = Field(default=None, min_length=1, max_length=1600)
    is_enabled: bool | None = None


class RuleTestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    recipient: str = "254700000000"
    order_ref: str | None = None


class ReorderRequest(BaseModel):
    rule_ids: list[int] = Field(min_length=1)


class ServiceAMessage(BaseModel):
    message_id: str = Field(min_length=1, max_length=255)
    recipient: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=10000)
    order_ref: str | None = Field(default=None, max_length=255)
    received_at: datetime | None = None


def rule_snapshot(rule: MappingRule) -> dict:
    return {
        "name": rule.name,
        "priority": rule.priority,
        "match_type": rule.match_type,
        "match_value": rule.match_value,
        "case_sensitive": rule.case_sensitive,
        "sender_id": rule.sender_id,
        "outbound_template": rule.outbound_template,
        "is_enabled": rule.is_enabled,
    }


def validate_rule(fields: dict) -> None:
    if fields["match_type"] == "regex":
        try:
            compiled = re.compile(fields["match_value"])
        except re.error as error:
            raise HTTPException(status_code=422, detail=f"Invalid regular expression: {error}") from error
        available = BUILTIN_PLACEHOLDERS | set(compiled.groupindex)
    else:
        available = BUILTIN_PLACEHOLDERS
    unknown = sorted(set(PLACEHOLDER_PATTERN.findall(fields["outbound_template"])) - available)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Template uses unavailable placeholders: {', '.join(unknown)}")


def match_rule(rule: MappingRule | dict, text: str):
    match_type = rule.match_type if isinstance(rule, MappingRule) else rule["match_type"]
    match_value = rule.match_value if isinstance(rule, MappingRule) else rule["match_value"]
    case_sensitive = rule.case_sensitive if isinstance(rule, MappingRule) else rule["case_sensitive"]
    flags = 0 if case_sensitive else re.IGNORECASE
    if match_type == "regex":
        match = re.search(match_value, text, flags)
        return match.groupdict() if match else None
    source = text if case_sensitive else text.casefold()
    expected = match_value if case_sensitive else match_value.casefold()
    matched = {
        "contains": expected in source,
        "starts_with": source.startswith(expected),
        "exact": source == expected,
    }[match_type]
    return {} if matched else None


def render_template(template: str, values: dict[str, str]) -> str:
    return PLACEHOLDER_PATTERN.sub(lambda match: values[match.group(1)], template)


def sms_segments(text: str) -> tuple[int, str, int]:
    if all(character in GSM_BASIC or character in GSM_EXTENDED for character in text):
        units = sum(2 if character in GSM_EXTENDED else 1 for character in text)
        return (1 if units <= 160 else math.ceil(units / 153), "GSM-7", units)
    units = len(text)
    return (1 if units <= 70 else math.ceil(units / 67), "Unicode", units)


def values_for(text: str, recipient: str, order_ref: str | None, groups: dict[str, str]) -> dict[str, str]:
    return {
        "recipient": recipient,
        "order_ref": order_ref or "",
        "original_text": text,
        "date": datetime.now(timezone.utc).date().isoformat(),
        **groups,
    }


def public_rule(rule: MappingRule) -> dict:
    return {"id": rule.id, **rule_snapshot(rule), "version": rule.version}


def add_audit(db: Session, actor: User, action: str, entity_id: str, before: dict | None, after: dict | None, request: Request):
    db.add(
        AuditLog(
            actor_id=actor.id,
            action=action,
            entity="mapping_rule",
            entity_id=entity_id,
            before=before,
            after=after,
            ip_address=request.client.host if request.client else None,
            created_at=datetime.now(timezone.utc),
        )
    )


def require_rule_editor(user: User = Depends(get_authenticated_user)) -> User:
    if user.role not in {"super_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


def within_time_window(current: str, start: str, end: str) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def load_configuration_value(db: Session) -> dict | None:
    record = db.scalar(select(SystemSetting).where(SystemSetting.key == "configuration"))
    return record.value if record else None


@router.get("/api/rules")
def list_rules(db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    rules = db.scalars(
        select(MappingRule).where(MappingRule.deleted_at.is_(None)).order_by(MappingRule.priority, MappingRule.id)
    ).all()
    return [public_rule(rule) for rule in rules]


@router.post("/api/rules", status_code=status.HTTP_201_CREATED)
def create_rule(fields: RuleFields, request: Request, db: Session = Depends(get_db), user: User = Depends(require_rule_editor)):
    data = fields.model_dump()
    validate_rule(data)
    now = datetime.now(timezone.utc)
    rule = MappingRule(**data, version=1, created_by=user.id, updated_by=user.id)
    db.add(rule)
    db.flush()
    db.add(MappingRuleVersion(rule_id=rule.id, version=1, snapshot=data, created_by=user.id, created_at=now))
    add_audit(db, user, "created", str(rule.id), None, data, request)
    db.commit()
    return public_rule(rule)


@router.patch("/api/rules/reorder")
def reorder_rules(payload: ReorderRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_rule_editor)):
    rules = db.scalars(
        select(MappingRule).where(MappingRule.id.in_(payload.rule_ids), MappingRule.deleted_at.is_(None))
    ).all()
    if len(rules) != len(payload.rule_ids) or len(set(payload.rule_ids)) != len(payload.rule_ids):
        raise HTTPException(status_code=422, detail="Provide each active rule ID exactly once")
    by_id = {rule.id: rule for rule in rules}
    now = datetime.now(timezone.utc)
    for priority, rule_id in enumerate(payload.rule_ids, start=1):
        rule = by_id[rule_id]
        before = rule_snapshot(rule)
        rule.priority = priority
        rule.version += 1
        rule.updated_by = user.id
        after = rule_snapshot(rule)
        db.add(MappingRuleVersion(rule_id=rule.id, version=rule.version, snapshot=after, created_by=user.id, created_at=now))
        add_audit(db, user, "reordered", str(rule.id), before, after, request)
    db.commit()
    return [public_rule(by_id[rule_id]) for rule_id in payload.rule_ids]


@router.post("/api/rules/test")
def test_rule(payload: RuleTestRequest, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    rules = db.scalars(
        select(MappingRule).where(MappingRule.deleted_at.is_(None)).order_by(MappingRule.priority, MappingRule.id)
    ).all()
    for rule in rules:
        groups = match_rule(rule, payload.text)
        if groups is None:
            continue
        rendered = render_template(
            rule.outbound_template,
            values_for(payload.text, payload.recipient, payload.order_ref, groups),
        )
        segments, encoding, units = sms_segments(rendered)
        return {
            "rule": public_rule(rule),
            "status": "Queued" if rule.is_enabled else "Suppressed",
            "rendered_text": rendered,
            "character_count": len(rendered),
            "encoding": encoding,
            "encoding_units": units,
            "segments": segments,
            "warnings": ["Message exceeds 3 SMS segments"] if segments > 3 else [],
        }
    return {"rule": None, "status": "Unmapped", "rendered_text": None, "segments": 0, "warnings": []}


@router.patch("/api/rules/{rule_id}")
def update_rule(rule_id: int, changes: RuleUpdate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_rule_editor)):
    rule = db.get(MappingRule, rule_id)
    if not rule or rule.deleted_at:
        raise HTTPException(status_code=404, detail="Rule not found")
    before = rule_snapshot(rule)
    updated = before | changes.model_dump(exclude_unset=True)
    validate_rule(updated)
    now = datetime.now(timezone.utc)
    for key, value in updated.items():
        setattr(rule, key, value)
    if rule.is_enabled is False:
        db.execute(
            update(InboundMessage)
            .where(InboundMessage.rule_id == rule.id, InboundMessage.status == "Queued")
            .values(status="Suppressed", status_reason="Mapping rule disabled")
        )
    rule.version += 1
    rule.updated_by = user.id
    db.add(MappingRuleVersion(rule_id=rule.id, version=rule.version, snapshot=updated, created_by=user.id, created_at=now))
    add_audit(db, user, "updated", str(rule.id), before, updated, request)
    db.commit()
    return public_rule(rule)


@router.delete("/api/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_rule_editor)):
    rule = db.get(MappingRule, rule_id)
    if not rule or rule.deleted_at:
        raise HTTPException(status_code=404, detail="Rule not found")
    before = rule_snapshot(rule)
    rule.deleted_at = datetime.now(timezone.utc)
    rule.version += 1
    rule.updated_by = user.id
    add_audit(db, user, "deleted", str(rule.id), before, None, request)
    db.commit()


@router.get("/api/rules/{rule_id}/versions")
def list_rule_versions(rule_id: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    rule = db.get(MappingRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    versions = db.scalars(
        select(MappingRuleVersion).where(MappingRuleVersion.rule_id == rule_id).order_by(MappingRuleVersion.version.desc())
    ).all()
    return [
        {"version": version.version, "snapshot": version.snapshot, "created_by": version.created_by, "created_at": version.created_at}
        for version in versions
    ]


@router.post("/api/rules/{rule_id}/versions/{version}/restore")
def restore_rule_version(rule_id: int, version: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_rule_editor)):
    rule = db.get(MappingRule, rule_id)
    if not rule or rule.deleted_at:
        raise HTTPException(status_code=404, detail="Rule not found")
    target = db.scalar(
        select(MappingRuleVersion).where(MappingRuleVersion.rule_id == rule_id, MappingRuleVersion.version == version)
    )
    if not target:
        raise HTTPException(status_code=404, detail="Rule version not found")
    before = rule_snapshot(rule)
    snapshot = target.snapshot
    validate_rule(snapshot)
    now = datetime.now(timezone.utc)
    for key, value in snapshot.items():
        setattr(rule, key, value)
    rule.version += 1
    rule.updated_by = user.id
    db.add(MappingRuleVersion(rule_id=rule.id, version=rule.version, snapshot=rule_snapshot(rule), created_by=user.id, created_at=now))
    add_audit(db, user, "restored", str(rule.id), before, rule_snapshot(rule), request)
    db.commit()
    return public_rule(rule)


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
            secret_key = settings.secret_encryption_key or settings.otp_pepper
            api_key = decrypt_secret(gateway["encrypted_api_key"], secret_key)
            client_id = decrypt_secret(gateway["encrypted_client_id"], secret_key)
            access_key = decrypt_secret(gateway["encrypted_access_key"], secret_key)
        except Exception:
            message.status = "Failed"
            message.error = "Gateway credentials could not be decrypted"
            db.commit()
            return
        rule = db.get(MappingRule, message.rule_id) if message.rule_id else None
        if not rule or not rule.is_enabled:
            message.status = "Suppressed"
            message.status_reason = "Mapping rule disabled before send"
            db.commit()
            return
        switch = db.scalar(select(SystemSetting).where(SystemSetting.key == "sending"))
        state = switch.value["state"] if switch else "on"
        if state != "on":
            message.status = "Skipped" if state == "stopped" else "Queued"
            message.status_reason = "Global sending is stopped" if state == "stopped" else "Global sending is paused"
            db.commit()
            return
        quiet_hours = configuration.value.get("quiet_hours", {}) if configuration else {}
        if quiet_hours.get("enabled"):
            from zoneinfo import ZoneInfo

            tz_name = configuration.value.get("timezone", "Africa/Nairobi") if configuration else "Africa/Nairobi"
            now_local = datetime.now(ZoneInfo(tz_name))
            if within_time_window(now_local.strftime("%H:%M"), quiet_hours.get("start", "21:00"), quiet_hours.get("end", "07:00")):
                message.status = "Queued"
                message.status_reason = "Queued: quiet hours active"
                db.commit()
                return
        recipient = normalize_kenyan_mobile(message.recipient)
        if not recipient:
            message.status = "Invalid recipient"
            message.status_reason = "Only Kenyan mobile numbers are accepted"
            db.commit()
            return
        message.recipient = recipient
        if not message.network:
            message.network = detect_network(recipient, (configuration.value.get("network_prefixes") if configuration else None) or DEFAULT_NETWORK_PREFIXES)
        segments, encoding, _ = sms_segments(message.rendered_text or "")
        limits = configuration.value.get("limits", {})
        max_segments = int(limits.get("max_segments", 3))
        if segments > max_segments:
            message.status = "Blocked"
            message.status_reason = f"Message exceeds the {max_segments}-segment limit"
            db.commit()
            return
        sender_id = message.sender_id or gateway.get("default_sender_id")
        if sender_id not in gateway.get("allowed_sender_ids", []):
            message.status = "Blocked"
            message.status_reason = "Sender ID is not in the allowed list"
            db.commit()
            return
        safety = configuration.value.get("safety", {})
        blocked = db.scalar(
            select(BlocklistEntry).where(BlocklistEntry.phone_number == recipient, BlocklistEntry.removed_at.is_(None))
        )
        if blocked:
            message.status = "Blocked"
            message.status_reason = "Recipient is on the blocklist"
            db.commit()
            return
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
            message.status = "Blocked"
            message.status_reason = "Duplicate message to this recipient"
            db.commit()
            return
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
            message.status = "Throttled"
            message.status_reason = "Recipient hourly message limit reached"
            db.commit()
            return
        if safety.get("test_mode") and recipient not in safety.get("test_allowlist", []):
            message.status = "Blocked"
            message.status_reason = "Recipient is not on the test-mode allowlist"
            db.commit()
            return
        billing = configuration.value.get("billing", {})
        network_rates = billing.get("network_rates", {})
        rate_value = network_rates.get(message.network) if message.network else None
        rate = Decimal(str(rate_value if rate_value is not None else billing.get("cost_per_segment_kes", "0.80")))
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

    adapter = ServiceBAdapter(gateway["base_url"], api_key, client_id, access_key)
    for attempt in range(retries):
        with session_factory() as db:
            message = db.get(InboundMessage, message_id)
            rule = db.get(MappingRule, message.rule_id) if message and message.rule_id else None
            switch = db.scalar(select(SystemSetting).where(SystemSetting.key == "sending"))
            state = switch.value["state"] if switch else "on"
            if not message or message.status != "Sending":
                return
            if not rule or not rule.is_enabled:
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


@router.post("/api/inbound/service-a", status_code=status.HTTP_202_ACCEPTED)
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