import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.alerts import send_alert
from app.analytics import compute_kpis, month_to_date_cost, period_bounds, resolve_timezone
from app.config import Settings
from app.configuration import DEFAULTS, with_defaults
from app.models import AuditLog, InboundMessage, SystemSetting

logger = logging.getLogger("upenflow.monitoring")


def load_configuration(db: Session) -> dict:
    record = db.scalar(select(SystemSetting).where(SystemSetting.key == "configuration"))
    return with_defaults(record.value) if record else {key: value.copy() if isinstance(value, dict) else value for key, value in DEFAULTS.items()}


def get_state(db: Session) -> dict:
    record = db.scalar(select(SystemSetting).where(SystemSetting.key == "monitoring_state"))
    return record.value.copy() if record else {}


def save_state(db: Session, state: dict) -> None:
    record = db.scalar(select(SystemSetting).where(SystemSetting.key == "monitoring_state"))
    now = datetime.now(timezone.utc)
    if record:
        record.value = state
        record.updated_at = now
    else:
        db.add(SystemSetting(key="monitoring_state", value=state, updated_at=now))
    db.commit()


def wake_queued_messages(session_factory, settings: Settings) -> None:
    from app.rules import deliver_queued_message

    with session_factory() as db:
        message_ids = db.scalars(select(InboundMessage.id).where(InboundMessage.status == "Queued")).all()
    for message_id in message_ids:
        try:
            deliver_queued_message(session_factory, message_id, settings)
        except Exception:
            logger.exception("queue_wake_failed", extra={"fields": {"message_id": message_id}})


def check_service_a_silence(db: Session, settings: Settings, configuration: dict) -> None:
    monitoring = configuration.get("monitoring", {})
    threshold = timedelta(minutes=int(monitoring.get("service_a_silence_minutes", 30)))
    tz = resolve_timezone(configuration)
    quiet = configuration.get("quiet_hours", {})
    now_local = datetime.now(tz)
    if quiet.get("enabled") and _within_window(now_local.strftime("%H:%M"), quiet.get("start", "21:00"), quiet.get("end", "07:00")):
        return
    latest = db.scalar(select(InboundMessage.received_at).order_by(InboundMessage.received_at.desc()).limit(1))
    if latest is None:
        return
    now = datetime.now(timezone.utc)
    if now - latest <= threshold:
        return
    state = get_state(db)
    marker = latest.isoformat()
    if state.get("service_a_alert_for") == marker:
        return
    send_alert(
        settings,
        configuration,
        "No messages from Service A",
        f"No inbound message has been received in over {monitoring.get('service_a_silence_minutes', 30)} minutes. Last message was received at {latest.isoformat()}.",
    )
    state["service_a_alert_for"] = marker
    save_state(db, state)


def check_service_b_health(db: Session, settings: Settings, configuration: dict) -> None:
    monitoring = configuration.get("monitoring", {})
    threshold_percent = int(monitoring.get("error_rate_threshold_percent", 20))
    window_start = datetime.now(timezone.utc) - timedelta(hours=1)
    rows = db.execute(
        select(InboundMessage.status, InboundMessage.id).where(
            InboundMessage.status.in_(["Sent", "Delivered", "Failed"]), InboundMessage.sent_at >= window_start
        )
    ).all()
    total = len(rows)
    if total < 5:
        return
    failed = sum(1 for status, _ in rows if status == "Failed")
    rate = failed / total * 100
    if rate <= threshold_percent:
        return
    state = get_state(db)
    marker = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    if state.get("service_b_alert_for") == marker:
        return
    send_alert(
        settings,
        configuration,
        "Service B error rate is high",
        f"{failed} of {total} sends failed in the last hour ({rate:.1f}%), above the {threshold_percent}% threshold.",
    )
    state["service_b_alert_for"] = marker
    save_state(db, state)


def check_budget_alert(db: Session, settings: Settings, configuration: dict) -> None:
    billing = configuration.get("billing", {})
    budget = Decimal(str(billing.get("monthly_budget_kes", "0")))
    if budget <= 0:
        return
    threshold_percent = int(billing.get("alert_threshold_percent", 80))
    tz = resolve_timezone(configuration)
    spend = month_to_date_cost(db, tz)
    used_percent = float(spend / budget * 100)
    if used_percent < threshold_percent:
        return
    state = get_state(db)
    month_marker = datetime.now(tz).strftime("%Y-%m")
    if state.get("budget_alert_month") == month_marker:
        return
    send_alert(
        settings,
        configuration,
        "Monthly SMS budget threshold reached",
        f"Spend this month is KES {spend:.2f}, which is {used_percent:.1f}% of the KES {budget:.2f} budget.",
    )
    state["budget_alert_month"] = month_marker
    save_state(db, state)


def check_low_credit(db: Session, settings: Settings, configuration: dict) -> None:
    gateway = configuration.get("gateway", {})
    monitoring = configuration.get("monitoring", {})
    balance_url = gateway.get("balance_url")
    if not balance_url:
        return
    low_credit = Decimal(str(monitoring.get("low_credit_kes", "1000")))
    try:
        import httpx

        response = httpx.get(balance_url, timeout=10.0)
        balance = Decimal(str(response.json().get("balance_kes", "0")))
    except Exception:
        return
    if balance >= low_credit:
        return
    state = get_state(db)
    day_marker = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("low_credit_alert_day") == day_marker:
        return
    send_alert(settings, configuration, "SMS gateway balance is low", f"Service B balance is KES {balance:.2f}, below the KES {low_credit:.2f} threshold.")
    state["low_credit_alert_day"] = day_marker
    save_state(db, state)


def send_daily_summary_if_due(db: Session, settings: Settings, configuration: dict) -> None:
    if not configuration.get("alert_emails"):
        return
    tz = resolve_timezone(configuration)
    now_local = datetime.now(tz)
    if now_local.hour != 8:
        return
    state = get_state(db)
    day_marker = now_local.strftime("%Y-%m-%d")
    if state.get("daily_summary_date") == day_marker:
        return
    start, end, prev_start, prev_end = period_bounds("daily", None, None, tz)
    yesterday_start, yesterday_end = start - timedelta(days=1), start
    kpis = compute_kpis(db, yesterday_start, yesterday_end, yesterday_start - timedelta(days=1), yesterday_start, None, None, None, None)
    body = "\n".join(f"{key}: {value['value']}" for key, value in kpis.items())
    send_alert(settings, configuration, "Daily SMS summary", body)
    state["daily_summary_date"] = day_marker
    save_state(db, state)


def send_monthly_report_if_due(db: Session, settings: Settings, configuration: dict) -> None:
    if not configuration.get("alert_emails"):
        return
    tz = resolve_timezone(configuration)
    now_local = datetime.now(tz)
    if now_local.day != 1 or now_local.hour != 8:
        return
    state = get_state(db)
    month_marker = now_local.strftime("%Y-%m")
    if state.get("monthly_report_month") == month_marker:
        return
    _, _, prev_start, prev_end = period_bounds("monthly", None, None, tz)
    before_prev = prev_start - (prev_end - prev_start)
    kpis = compute_kpis(db, prev_start, prev_end, before_prev, prev_start, None, None, None, None)
    body = "\n".join(f"{key}: {value['value']}" for key, value in kpis.items())
    send_alert(settings, configuration, "Monthly SMS cost report", body)
    state["monthly_report_month"] = month_marker
    save_state(db, state)


def purge_old_data(db: Session, configuration: dict) -> None:
    retention = configuration.get("retention", {})
    now = datetime.now(timezone.utc)
    state = get_state(db)
    day_marker = now.strftime("%Y-%m-%d")
    if state.get("purge_date") == day_marker:
        return
    message_cutoff = now - timedelta(days=int(retention.get("message_retention_days", 180)))
    audit_cutoff = now - timedelta(days=int(retention.get("audit_log_retention_days", 730)))
    terminal_statuses = [
        "Sent", "Delivered", "Failed", "Skipped", "Suppressed", "Blocked", "Invalid recipient", "Unmapped", "Throttled",
    ]
    db.execute(delete(InboundMessage).where(InboundMessage.received_at < message_cutoff, InboundMessage.status.in_(terminal_statuses)))
    db.execute(delete(AuditLog).where(AuditLog.created_at < audit_cutoff))
    state["purge_date"] = day_marker
    save_state(db, state)


def _within_window(current: str, start: str, end: str) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def run_once(session_factory, settings: Settings) -> None:
    wake_queued_messages(session_factory, settings)
    with session_factory() as db:
        configuration = load_configuration(db)
        check_service_a_silence(db, settings, configuration)
        check_service_b_health(db, settings, configuration)
        check_budget_alert(db, settings, configuration)
        check_low_credit(db, settings, configuration)
        send_daily_summary_if_due(db, settings, configuration)
        send_monthly_report_if_due(db, settings, configuration)
        purge_old_data(db, configuration)


async def scheduler_loop(session_factory, settings: Settings) -> None:
    while True:
        try:
            await asyncio.to_thread(run_once, session_factory, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scheduler_tick_failed")
        try:
            await asyncio.sleep(settings.scheduler_interval_seconds)
        except asyncio.CancelledError:
            raise
