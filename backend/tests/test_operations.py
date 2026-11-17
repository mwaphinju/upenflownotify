import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import monitoring, rules
from app.config import Settings
from app.main import create_app
from app.models import AuditLog, BlocklistEntry, InboundMessage, MappingRule, SystemSetting, User, UserSession
from app.phone import detect_network
from app.security import token_hash


@pytest.fixture
def ops_client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'ops.db'}",
        otp_pepper="ops-pepper",
        cookie_secure=False,
        service_a_api_key="api-key",
        service_a_hmac_secret="hmac-secret",
        service_b_dlr_api_key="dlr-key",
        service_b_dlr_hmac_secret="dlr-secret",
        service_b_reply_api_key="reply-key",
        enable_scheduler=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        with app.state.session_factory() as db:
            user = User(name="Admin", email="admin@example.com", password_hash="unused", role="super_admin")
            db.add(user)
            db.flush()
            db.add(UserSession(user_id=user.id, token_hash=token_hash("admin-token"), created_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc)))
            db.commit()
        client.cookies.set("upenflow_session", "admin-token")
        yield client, app


def create_rule(client, **overrides):
    data = {
        "name": "Dispatched", "priority": 10, "match_type": "contains", "match_value": "dispatched",
        "case_sensitive": False, "sender_id": "UPENFLOW", "outbound_template": "Order {{order_ref}} dispatched", "is_enabled": True,
    }
    data.update(overrides)
    return client.post("/api/rules", json=data)


def post_inbound(client, message_id, recipient="0712345678", text="Order dispatched", order_ref=None):
    timestamp = str(int(time.time()))
    body = json.dumps({"message_id": message_id, "recipient": recipient, "text": text, "order_ref": order_ref or message_id}, separators=(",", ":")).encode()
    signature = hmac.new(b"hmac-secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return client.post("/api/inbound/service-a", content=body, headers={
        "Content-Type": "application/json", "X-Service-A-Key": "api-key",
        "X-Service-A-Timestamp": timestamp, "X-Service-A-Signature": signature,
    })


def post_dlr(client, provider_message_id, status, key="dlr-key", secret=b"dlr-secret"):
    timestamp = str(int(time.time()))
    body = json.dumps({"provider_message_id": provider_message_id, "status": status}, separators=(",", ":")).encode()
    signature = hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return client.post("/api/dlr/service-b", content=body, headers={
        "Content-Type": "application/json", "X-Service-B-Key": key,
        "X-Service-B-Timestamp": timestamp, "X-Service-B-Signature": signature,
    })


def configure_gateway(client):
    return client.patch("/api/settings", json={
        "gateway": {"base_url": "https://gateway.example.com/send", "api_key": "fake-secret", "default_sender_id": "UPENFLOW", "allowed_sender_ids": ["UPENFLOW"]},
    })


def test_network_detection_for_known_prefixes():
    assert detect_network("254712345678") == "Safaricom"
    assert detect_network("254733123456") == "Airtel"
    assert detect_network("254772123456") == "Telkom"
    assert detect_network("254799999999") is None or detect_network("254799999999") == "Safaricom"


def test_inbound_message_is_tagged_with_network(ops_client):
    client, app = ops_client
    assert create_rule(client).status_code == 201
    assert post_inbound(client, "net-1", "0712345678").status_code == 202
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "net-1"))
        assert message.network == "Safaricom"


def test_rule_version_history_and_rollback(ops_client):
    client, app = ops_client
    created = create_rule(client, outbound_template="Order {{order_ref}} dispatched").json()
    client.patch(f"/api/rules/{created['id']}", json={"outbound_template": "Updated {{order_ref}}"})

    versions = client.get(f"/api/rules/{created['id']}/versions").json()
    assert [version["version"] for version in versions] == [2, 1]
    assert versions[1]["snapshot"]["outbound_template"] == "Order {{order_ref}} dispatched"

    restored = client.post(f"/api/rules/{created['id']}/versions/1/restore")
    assert restored.status_code == 200
    assert restored.json()["outbound_template"] == "Order {{order_ref}} dispatched"
    assert restored.json()["version"] == 3

    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.com"))
        user.role = "viewer"
        db.commit()
    assert client.post(f"/api/rules/{created['id']}/versions/1/restore").status_code == 403


def test_resend_requeues_failed_message(ops_client, monkeypatch):
    client, app = ops_client
    assert create_rule(client).status_code == 201
    assert configure_gateway(client).status_code == 200

    class FailingAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, sender_id, to, text, message_key):
            from app.service_b import ServiceBError
            raise ServiceBError("boom", retryable=False)

    monkeypatch.setattr(rules, "ServiceBAdapter", FailingAdapter)
    assert post_inbound(client, "resend-1").status_code == 202
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "resend-1"))
        assert message.status == "Failed"
        message_id = message.id

    class WorkingAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, sender_id, to, text, message_key):
            return "provider-resend-1"

    monkeypatch.setattr(rules, "ServiceBAdapter", WorkingAdapter)
    resent = client.post(f"/api/messages/{message_id}/resend")
    assert resent.status_code == 200
    with app.state.session_factory() as db:
        message = db.get(InboundMessage, message_id)
        assert message.status == "Sent"
        assert message.provider_message_id == "provider-resend-1"

    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.com"))
        user.role = "viewer"
        db.commit()
    assert client.post(f"/api/messages/{message_id}/resend").status_code == 403


def test_resend_is_not_double_claimable(ops_client, monkeypatch):
    client, app = ops_client
    assert create_rule(client).status_code == 201
    assert configure_gateway(client).status_code == 200

    class FailingAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, sender_id, to, text, message_key):
            from app.service_b import ServiceBError
            raise ServiceBError("boom", retryable=False)

    monkeypatch.setattr(rules, "ServiceBAdapter", FailingAdapter)
    assert post_inbound(client, "resend-race-1").status_code == 202
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "resend-race-1"))
        assert message.status == "Failed"
        message_id = message.id

    monkeypatch.setattr(rules, "enqueue_delivery", lambda *args, **kwargs: None)
    first = client.post(f"/api/messages/{message_id}/resend")
    second = client.post(f"/api/messages/{message_id}/resend")
    assert first.status_code == 200
    assert second.status_code == 409
    with app.state.session_factory() as db:
        resend_logs = db.scalars(select(AuditLog).where(AuditLog.action == "message_resent", AuditLog.entity_id == str(message_id))).all()
        assert len(resend_logs) == 1


def test_customer_timeline_lists_messages_for_number(ops_client):
    client, app = ops_client
    assert create_rule(client).status_code == 201
    assert post_inbound(client, "timeline-1", "0712345678").status_code == 202
    assert post_inbound(client, "timeline-2", "0712345678").status_code == 202
    assert post_inbound(client, "timeline-3", "0711111111").status_code == 202

    timeline = client.get("/api/customers/0712345678/timeline").json()
    assert len(timeline["messages"]) == 2
    assert timeline["phone_number"] == "254712345678"
    assert client.get("/api/customers/0201234567/timeline").status_code == 422


def test_quiet_hours_holds_messages_until_window_ends(ops_client, monkeypatch):
    client, app = ops_client
    assert create_rule(client).status_code == 201
    assert configure_gateway(client).status_code == 200
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(minutes=1)).strftime("%H:%M")
    window_end = (now + timedelta(hours=1)).strftime("%H:%M")
    configured = client.patch("/api/settings", json={"quiet_hours": {"enabled": True, "start": window_start, "end": window_end}, "timezone": "UTC"})
    assert configured.status_code == 200

    sent = []

    class FakeAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, sender_id, to, text, message_key):
            sent.append(message_key)
            return "provider-quiet"

    monkeypatch.setattr(rules, "ServiceBAdapter", FakeAdapter)
    assert post_inbound(client, "quiet-1").status_code == 202
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "quiet-1"))
        assert message.status == "Queued"
        assert message.status_reason == "Queued: quiet hours active"
    assert sent == []

    client.patch("/api/settings", json={"quiet_hours": {"enabled": False}})
    monitoring.wake_queued_messages(app.state.session_factory, app.state.settings)
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "quiet-1"))
        assert message.status == "Sent"
    assert sent == ["quiet-1"]


def test_dlr_rejects_unauthenticated_and_bad_signature_requests(ops_client):
    client, app = ops_client
    assert create_rule(client).status_code == 201
    assert configure_gateway(client).status_code == 200
    unauthenticated = client.post("/api/dlr/service-b", json={"provider_message_id": "whatever", "status": "delivered"})
    assert unauthenticated.status_code == 401
    bad_signature = post_dlr(client, "whatever", "delivered", secret=b"wrong-secret")
    assert bad_signature.status_code == 401


def test_service_b_stop_reply_blocklists_number(ops_client):
    client, app = ops_client
    reply = client.post(
        "/api/inbound/service-b-reply",
        json={"sender": "0712345678", "text": "stop"},
        headers={"X-Service-B-Key": "reply-key"},
    )
    assert reply.status_code == 202
    assert reply.json()["blocked"] is True
    with app.state.session_factory() as db:
        entry = db.scalar(select(BlocklistEntry).where(BlocklistEntry.phone_number == "254712345678"))
        assert entry is not None
        assert entry.removed_at is None

    unauthenticated = client.post("/api/inbound/service-b-reply", json={"sender": "0712345678", "text": "stop"})
    assert unauthenticated.status_code == 401


def test_budget_alert_fires_once_per_month(ops_client):
    client, app = ops_client
    client.patch("/api/settings", json={"billing": {"monthly_budget_kes": "10.00", "alert_threshold_percent": 50}, "alert_emails": ["ops@example.com"]})
    with app.state.session_factory() as db:
        db.add(InboundMessage(
            source_message_id="cost-1", recipient="254712345678", text="x", raw_payload={}, received_at=datetime.now(timezone.utc),
            status="Sent", cost_kes=Decimal("8.00"),
        ))
        db.commit()

    sent_subjects = []
    import app.monitoring as monitoring_module
    original_send_alert = monitoring_module.send_alert

    def fake_send_alert(settings, configuration, subject, message):
        sent_subjects.append(subject)

    monitoring_module.send_alert = fake_send_alert
    try:
        with app.state.session_factory() as db:
            configuration = monitoring.load_configuration(db)
            monitoring.check_budget_alert(db, app.state.settings, configuration)
            monitoring.check_budget_alert(db, app.state.settings, configuration)
    finally:
        monitoring_module.send_alert = original_send_alert

    assert sent_subjects == ["Monthly SMS budget threshold reached"]


def test_dashboard_kpis_and_exports(ops_client, monkeypatch):
    client, app = ops_client
    assert create_rule(client).status_code == 201
    assert configure_gateway(client).status_code == 200

    class FakeAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, sender_id, to, text, message_key):
            return f"provider-{message_key}"

    monkeypatch.setattr(rules, "ServiceBAdapter", FakeAdapter)
    assert post_inbound(client, "dash-1").status_code == 202
    assert post_inbound(client, "dash-2", "0711111111").status_code == 202

    dashboard = client.get("/api/dashboard", params={"period": "daily"}).json()
    assert dashboard["kpis"]["sent"]["value"] == 2
    assert dashboard["kpis"]["total_cost_kes"]["value"] > 0
    assert dashboard["charts"]["by_network"]
    assert len(dashboard["charts"]["hour_heatmap"]) == 24

    csv_export = client.get("/api/dashboard/export.csv", params={"period": "daily"})
    assert csv_export.status_code == 200
    assert b"sent" in csv_export.content

    pdf_export = client.get("/api/dashboard/export.pdf", params={"period": "daily"})
    assert pdf_export.status_code == 200
    assert pdf_export.content.startswith(b"%PDF")


def test_retention_purge_deletes_old_terminal_messages(ops_client):
    client, app = ops_client
    old = datetime.now(timezone.utc) - timedelta(days=400)
    with app.state.session_factory() as db:
        db.add(InboundMessage(source_message_id="old-1", recipient="254712345678", text="x", raw_payload={}, received_at=old, status="Sent"))
        db.add(InboundMessage(source_message_id="recent-1", recipient="254712345678", text="x", raw_payload={}, received_at=datetime.now(timezone.utc), status="Sent"))
        db.commit()

    with app.state.session_factory() as db:
        configuration = monitoring.load_configuration(db)
        configuration["retention"]["message_retention_days"] = 180
        monitoring.purge_old_data(db, configuration)

    with app.state.session_factory() as db:
        remaining = {row.source_message_id for row in db.scalars(select(InboundMessage)).all()}
        assert remaining == {"recent-1"}
