import csv
import io
import math
from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.analytics import compute_kpis, chart_data, period_bounds, resolve_timezone
from app.auth import get_authenticated_user
from app.configuration import DEFAULTS, with_defaults
from app.database import get_db
from app.models import AuditLog, InboundMessage, MappingRule, MappingRuleVersion, SystemSetting, User
from app.phone import mask_phone, normalize_kenyan_mobile


router = APIRouter(tags=["notifications", "dashboard"])


def visible_recipient(user: User, value: str) -> str:
    return value if user.role == "super_admin" else mask_phone(value)


def load_configuration(db: Session) -> dict:
    record = db.scalar(select(SystemSetting).where(SystemSetting.key == "configuration"))
    return with_defaults(record.value) if record else {key: value.copy() if isinstance(value, dict) else value for key, value in DEFAULTS.items()}


def message_query(
    search: str | None,
    status: str | None,
    rule_id: int | None,
    sender_id: str | None,
    network: str | None,
    from_date: datetime | None,
    to_date: datetime | None,
):
    query = select(InboundMessage)
    if search:
        normalized = normalize_kenyan_mobile(search)
        clauses = [
            InboundMessage.source_message_id.ilike(f"%{search}%"),
            InboundMessage.text.ilike(f"%{search}%"),
            InboundMessage.order_ref.ilike(f"%{search}%"),
            InboundMessage.rendered_text.ilike(f"%{search}%"),
        ]
        if normalized:
            clauses.append(InboundMessage.recipient == normalized)
        query = query.where(or_(*clauses))
    if status:
        query = query.where(InboundMessage.status == status)
    if rule_id is not None:
        query = query.where(InboundMessage.rule_id == rule_id)
    if sender_id:
        query = query.where(InboundMessage.sender_id == sender_id)
    if network:
        query = query.where(InboundMessage.network == network)
    if from_date:
        query = query.where(InboundMessage.received_at >= from_date)
    if to_date:
        query = query.where(InboundMessage.received_at < to_date)
    return query


def list_row(message: InboundMessage, user: User) -> dict:
    return {
        "id": message.id,
        "message_id": message.source_message_id,
        "received_at": message.received_at,
        "recipient": visible_recipient(user, message.recipient),
        "order_ref": message.order_ref,
        "rule_id": message.rule_id,
        "sender_id": message.sender_id,
        "network": message.network,
        "segments": message.segments,
        "cost_kes": float(message.cost_kes) if message.cost_kes is not None else None,
        "inbound_preview": message.text[:120],
        "sms_preview": message.rendered_text[:120] if message.rendered_text else None,
        "status": message.status,
        "status_reason": message.status_reason,
    }


@router.get("/api/messages")
def list_messages(
    search: str | None = None,
    status: str | None = None,
    rule_id: int | None = None,
    sender_id: str | None = None,
    network: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
):
    query = message_query(search, status, rule_id, sender_id, network, from_date, to_date)
    count = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(InboundMessage.received_at.desc(), InboundMessage.id.desc()).offset((page - 1) * 50).limit(50)).all()
    return {"items": [list_row(row, user) for row in rows], "page": page, "per_page": 50, "total": count, "pages": math.ceil(count / 50)}


@router.get("/api/messages/export.csv")
def export_messages(
    search: str | None = None,
    status: str | None = None,
    rule_id: int | None = None,
    sender_id: str | None = None,
    network: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
):
    if user.role not in {"super_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Export permission required")
    rows = db.scalars(message_query(search, status, rule_id, sender_id, network, None, None).order_by(InboundMessage.received_at.desc())).all()
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["received_at", "message_id", "recipient", "order_ref", "network", "segments", "cost_kes", "status", "sender_id", "inbound_text", "rendered_text"])
    for row in rows:
        writer.writerow([
            row.received_at.isoformat(), row.source_message_id, visible_recipient(user, row.recipient), row.order_ref or "",
            row.network or "", row.segments or "", row.cost_kes if row.cost_kes is not None else "", row.status, row.sender_id or "",
            row.text, row.rendered_text or "",
        ])
    return Response(content=stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=notifications.csv"})


def message_timeline(message: InboundMessage) -> list[dict]:
    events = [{"status": "Received", "at": message.received_at}]
    if message.sent_at:
        events.append({"status": "Sent", "at": message.sent_at})
    if message.delivered_at:
        events.append({"status": "Delivered", "at": message.delivered_at})
    if message.status not in {"Received", "Sent", "Delivered"} and message.status not in [event["status"] for event in events]:
        events.append({"status": message.status, "at": None})
    return events


@router.get("/api/messages/{message_id}")
def get_message(message_id: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    message = db.get(InboundMessage, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    rule = db.get(MappingRule, message.rule_id) if message.rule_id else None
    version = db.get(MappingRuleVersion, message.rule_version_id) if message.rule_version_id else None
    return {
        **list_row(message, user),
        "recipient": visible_recipient(user, message.recipient),
        "inbound_text": message.text,
        "rendered_text": message.rendered_text,
        "raw_payload": message.raw_payload,
        "rule": rule.name if rule else None,
        "rule_version": version.version if version else None,
        "rate_per_segment_kes": float(message.rate_per_segment_kes) if message.rate_per_segment_kes is not None else None,
        "attempts": message.attempts,
        "error": message.error,
        "provider_message_id": message.provider_message_id,
        "timeline": message_timeline(message),
        "can_resend": message.status in {"Failed", "Blocked", "Invalid recipient"} and user.role in {"super_admin", "operator"},
    }


@router.post("/api/messages/{message_id}/resend")
def resend_message(message_id: int, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    if user.role not in {"super_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    message = db.get(InboundMessage, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    resendable_statuses = ["Failed", "Blocked", "Invalid recipient"]
    if message.status not in resendable_statuses:
        raise HTTPException(status_code=409, detail="Only failed or blocked messages can be resent")
    before_status = message.status
    claimed = db.execute(
        update(InboundMessage)
        .where(InboundMessage.id == message.id, InboundMessage.status.in_(resendable_statuses))
        .values(status="Queued", status_reason="Resent by operator", error=None)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="This message was already resent")
    db.add(
        AuditLog(
            actor_id=user.id,
            action="message_resent",
            entity="message",
            entity_id=str(message.id),
            before={"status": before_status},
            after={"status": "Queued"},
            ip_address=request.client.host if request.client else None,
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    from app.delivery import enqueue_delivery

    enqueue_delivery(request, background_tasks, message.id)
    return {"status": "Queued"}


@router.get("/api/customers/{phone}/timeline")
def customer_timeline(phone: str, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    number = normalize_kenyan_mobile(phone)
    if not number:
        raise HTTPException(status_code=422, detail="Only Kenyan mobile numbers are accepted")
    rows = db.scalars(
        select(InboundMessage).where(InboundMessage.recipient == number).order_by(InboundMessage.received_at.desc()).limit(200)
    ).all()
    return {"phone_number": visible_recipient(user, number), "messages": [list_row(row, user) for row in rows]}


@router.get("/api/dashboard")
def dashboard(
    period: str = Query(default="weekly", pattern="^(daily|weekly|monthly|custom)$"),
    start: date | None = None,
    end: date | None = None,
    rule_id: int | None = None,
    sender_id: str | None = None,
    network: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
):
    configuration = load_configuration(db)
    tz = resolve_timezone(configuration)
    try:
        period_start, period_end, prev_start, prev_end = period_bounds(period, start, end, tz)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    kpis = compute_kpis(db, period_start, period_end, prev_start, prev_end, rule_id, sender_id, network, status)
    charts = chart_data(db, period_start, period_end, rule_id, sender_id, network, status, tz)
    billing = configuration.get("billing", {})
    budget = float(billing.get("monthly_budget_kes", 0) or 0)
    sending = db.scalar(select(SystemSetting).where(SystemSetting.key == "sending"))
    queued = db.scalar(select(func.count()).select_from(InboundMessage).where(InboundMessage.status == "Queued")) or 0
    month_to_date = sum(item["cost_kes"] for item in charts["timeseries"]) if period == "monthly" else kpis["total_cost_kes"]["value"]
    return {
        "period": {
            "label": period,
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "previous_start": prev_start.isoformat(),
            "previous_end": prev_end.isoformat(),
        },
        "kpis": kpis,
        "budget_kes": budget,
        "budget_used_percent": round(month_to_date / budget * 100, 1) if budget else 0.0,
        "charts": charts,
        "sending_state": sending.value["state"] if sending else "on",
        "queued": queued,
        "test_mode": configuration.get("safety", {}).get("test_mode", False),
    }


@router.get("/api/dashboard/export.csv")
def export_dashboard(
    period: str = Query(default="weekly", pattern="^(daily|weekly|monthly|custom)$"),
    start: date | None = None,
    end: date | None = None,
    rule_id: int | None = None,
    sender_id: str | None = None,
    network: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
):
    if user.role not in {"super_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Export permission required")
    configuration = load_configuration(db)
    tz = resolve_timezone(configuration)
    period_start, period_end, prev_start, prev_end = period_bounds(period, start, end, tz)
    kpis = compute_kpis(db, period_start, period_end, prev_start, prev_end, rule_id, sender_id, network, status)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["metric", "value", "change_percent"])
    for key, item in kpis.items():
        writer.writerow([key, item["value"], item["change_percent"]])
    return Response(content=stream.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=dashboard-summary.csv"})


@router.get("/api/dashboard/export.pdf")
def export_dashboard_pdf(
    period: str = Query(default="weekly", pattern="^(daily|weekly|monthly|custom)$"),
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_authenticated_user),
):
    if user.role not in {"super_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Export permission required")
    configuration = load_configuration(db)
    tz = resolve_timezone(configuration)
    period_start, period_end, prev_start, prev_end = period_bounds(period, start, end, tz)
    kpis = compute_kpis(db, period_start, period_end, prev_start, prev_end, None, None, None, None)
    from app.reports import render_kpi_pdf

    pdf_bytes = render_kpi_pdf(f"Upenflow Notify — {period} summary", kpis)
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=dashboard-summary.pdf"})