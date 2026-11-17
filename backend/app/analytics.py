from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import InboundMessage, MappingRule

SENT_LIKE = ("Sent", "Delivered")
ATTEMPTED = ("Sent", "Delivered", "Failed")


def resolve_timezone(configuration: dict) -> ZoneInfo:
    try:
        return ZoneInfo(configuration.get("timezone") or "Africa/Nairobi")
    except Exception:
        return ZoneInfo("Africa/Nairobi")


def period_bounds(period: str, start_param: date | None, end_param: date | None, tz: ZoneInfo):
    now_local = datetime.now(tz)
    if period == "daily":
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        prev_start_local = start_local - timedelta(days=1)
        prev_end_local = start_local
    elif period == "weekly":
        start_local = (now_local - timedelta(days=now_local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=7)
        prev_start_local = start_local - timedelta(days=7)
        prev_end_local = start_local
    elif period == "monthly":
        start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (start_local.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_local = next_month
        prev_month_end = start_local
        prev_month_start = (start_local - timedelta(days=1)).replace(day=1)
        prev_start_local, prev_end_local = prev_month_start, prev_month_end
    else:
        if not start_param or not end_param:
            raise ValueError("start and end are required for a custom period")
        start_local = datetime.combine(start_param, datetime.min.time(), tzinfo=tz)
        end_local = datetime.combine(end_param, datetime.min.time(), tzinfo=tz) + timedelta(days=1)
        span = end_local - start_local
        prev_start_local = start_local - span
        prev_end_local = start_local
    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
        prev_start_local.astimezone(timezone.utc),
        prev_end_local.astimezone(timezone.utc),
    )


def apply_filters(query: Select, rule_id: int | None, sender_id: str | None, network: str | None, status: str | None) -> Select:
    if rule_id is not None:
        query = query.where(InboundMessage.rule_id == rule_id)
    if sender_id:
        query = query.where(InboundMessage.sender_id == sender_id)
    if network:
        query = query.where(InboundMessage.network == network)
    if status:
        query = query.where(InboundMessage.status == status)
    return query


def filtered_query(start: datetime, end: datetime, rule_id: int | None, sender_id: str | None, network: str | None, status: str | None) -> Select:
    query = select(InboundMessage).where(InboundMessage.received_at >= start, InboundMessage.received_at < end)
    return apply_filters(query, rule_id, sender_id, network, status)


def change_percent(current: float, previous: float) -> float:
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round((current - previous) / previous * 100, 1)


def kpi_counts(db: Session, start: datetime, end: datetime, rule_id, sender_id, network, status) -> dict:
    base = select(InboundMessage.status, func.count(), func.coalesce(func.sum(InboundMessage.cost_kes), 0)).where(
        InboundMessage.received_at >= start, InboundMessage.received_at < end
    )
    base = apply_filters(base, rule_id, sender_id, network, status)
    rows = db.execute(base.group_by(InboundMessage.status)).all()
    counts = {status_value: count for status_value, count, _ in rows}
    cost = sum((Decimal(str(cost_value)) for _, _, cost_value in rows), Decimal(0))
    received = sum(counts.values())
    sent = sum(counts.get(key, 0) for key in SENT_LIKE)
    delivered = counts.get("Delivered", 0)
    failed = counts.get("Failed", 0)
    attempted = sum(counts.get(key, 0) for key in ATTEMPTED)
    unmapped = counts.get("Unmapped", 0)
    completed = sent + failed
    return {
        "received": received,
        "sent": sent,
        "delivered": delivered,
        "delivered_rate": round(delivered / sent * 100, 1) if sent else 0.0,
        "failed": failed,
        "failed_rate": round(failed / completed * 100, 1) if completed else 0.0,
        "unmapped": unmapped,
        "total_cost_kes": float(cost),
        "avg_cost_per_sms_kes": round(float(cost) / sent, 4) if sent else 0.0,
        "attempted": attempted,
    }


def compute_kpis(db: Session, start: datetime, end: datetime, prev_start: datetime, prev_end: datetime, rule_id, sender_id, network, status) -> dict:
    current = kpi_counts(db, start, end, rule_id, sender_id, network, status)
    previous = kpi_counts(db, prev_start, prev_end, rule_id, sender_id, network, status)
    result = {}
    for key in ("received", "sent", "delivered", "failed", "unmapped", "total_cost_kes", "avg_cost_per_sms_kes"):
        result[key] = {"value": current[key], "change_percent": change_percent(current[key], previous[key])}
    result["delivered"]["rate"] = current["delivered_rate"]
    result["failed"]["rate"] = current["failed_rate"]
    return result


def month_to_date_cost(db: Session, tz: ZoneInfo) -> Decimal:
    now_local = datetime.now(tz)
    start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = now_local.astimezone(timezone.utc)
    return db.scalar(
        select(func.coalesce(func.sum(InboundMessage.cost_kes), 0)).where(
            InboundMessage.received_at >= start_utc, InboundMessage.received_at < end_utc
        )
    ) or Decimal(0)


def chart_data(db: Session, start: datetime, end: datetime, rule_id, sender_id, network, status, tz: ZoneInfo) -> dict:
    granularity_hours = (end - start) <= timedelta(days=2)
    query = select(
        InboundMessage.received_at, InboundMessage.status, InboundMessage.cost_kes, InboundMessage.rule_id, InboundMessage.network
    ).where(InboundMessage.received_at >= start, InboundMessage.received_at < end)
    query = apply_filters(query, rule_id, sender_id, network, status)
    rows = db.execute(query).all()
    buckets: dict[str, dict] = {}
    hour_heatmap = [0] * 24
    rule_totals: dict[int, dict] = {}
    network_totals: dict[str, int] = {}
    for received_at, status_value, cost_kes, rule_id_value, network_value in rows:
        local = received_at.astimezone(tz)
        bucket_key = local.strftime("%Y-%m-%dT%H:00") if granularity_hours else local.strftime("%Y-%m-%d")
        bucket = buckets.setdefault(bucket_key, {"sent": 0, "delivered": 0, "failed": 0, "cost_kes": 0.0})
        if status_value in SENT_LIKE:
            bucket["sent"] += 1
        if status_value == "Delivered":
            bucket["delivered"] += 1
        if status_value == "Failed":
            bucket["failed"] += 1
        bucket["cost_kes"] += float(cost_kes or 0)
        hour_heatmap[local.hour] += 1
        if rule_id_value is not None:
            totals = rule_totals.setdefault(rule_id_value, {"count": 0, "cost_kes": 0.0})
            totals["count"] += 1
            totals["cost_kes"] += float(cost_kes or 0)
        if network_value:
            network_totals[network_value] = network_totals.get(network_value, 0) + 1
    timeseries = [{"period": key, **value} for key, value in sorted(buckets.items())]
    rule_names = dict(db.execute(select(MappingRule.id, MappingRule.name).where(MappingRule.id.in_(rule_totals.keys()))).all()) if rule_totals else {}
    by_rule = sorted(
        [{"rule": rule_names.get(rule_id_value, "Unknown"), **totals} for rule_id_value, totals in rule_totals.items()],
        key=lambda item: item["count"],
        reverse=True,
    )[:10]
    by_network = sorted([{"network": key, "count": value} for key, value in network_totals.items()], key=lambda item: item["count"], reverse=True)
    return {
        "granularity": "hour" if granularity_hours else "day",
        "timeseries": timeseries,
        "by_rule": by_rule,
        "by_network": by_network,
        "hour_heatmap": [{"hour": hour, "count": count} for hour, count in enumerate(hour_heatmap)],
    }
