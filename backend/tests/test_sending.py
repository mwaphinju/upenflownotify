import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import AuditLog, InboundMessage, MappingRule, User, UserSession
from app.security import token_hash
from app import rules


@pytest.fixture
def sending_client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'sending.db'}",
        otp_pepper="sending-test-pepper",
        cookie_secure=False,
        service_a_api_key="api-key",
        service_a_hmac_secret="hmac-secret",
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


def create_rule(client):
    return client.post("/api/rules", json={
        "name": "Dispatched", "priority": 10, "match_type": "contains", "match_value": "dispatched",
        "case_sensitive": False, "sender_id": "UPENFLOW", "outbound_template": "Order {{order_ref}} dispatched", "is_enabled": True,
    })


def post_inbound(client, message_id, recipient="0712345678", order_ref=None):
    timestamp = str(int(time.time()))
    body = json.dumps({"message_id": message_id, "recipient": recipient, "text": "Order dispatched", "order_ref": order_ref or message_id}, separators=(",", ":")).encode()
    signature = hmac.new(b"hmac-secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return client.post("/api/inbound/service-a", content=body, headers={
        "Content-Type": "application/json", "X-Service-A-Key": "api-key",
        "X-Service-A-Timestamp": timestamp, "X-Service-A-Signature": signature,
    })


def post_dlr(client, provider_message_id, status, error=None):
    # Mirrors Onfon's real push-DLR contract: a plain GET with these query params, no body.
    params = {"messageId": provider_message_id, "status": status, "errorCode": "0" if status == "delivered" else "1"}
    if error:
        params["shortMessage"] = error
    return client.get("/api/dlr/service-b", params=params)


def test_paused_messages_queue_and_discard_is_audited(sending_client):
    client, app = sending_client
    assert create_rule(client).status_code == 201
    paused = client.put("/api/settings/sending", json={"state": "paused", "confirmed": True, "reason": "Gateway maintenance"})
    assert paused.status_code == 200
    assert post_inbound(client, "pause-1").status_code == 202
    assert client.get("/api/settings/sending").json() == {"state": "paused", "queued_count": 1, "test_mode": False}
    assert client.put("/api/settings/sending", json={"state": "on", "confirmed": True, "reason": "Maintenance complete"}).status_code == 422

    resumed = client.put("/api/settings/sending", json={
        "state": "on", "confirmed": True, "reason": "Discard old queue", "resume_policy": "discard_all",
    })

    assert resumed.status_code == 200
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "pause-1"))
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "sending_state_changed").order_by(AuditLog.id.desc()))
        assert message.status == "Skipped"
        assert audit.reason == "Discard old queue"
        assert audit.before == {"state": "paused"}
        assert audit.after == {"state": "on"}


def test_stopped_messages_are_never_queued_and_operator_cannot_change_switch(sending_client):
    client, app = sending_client
    assert create_rule(client).status_code == 201
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.com"))
        user.role = "operator"
        db.commit()
    assert client.put("/api/settings/sending", json={"state": "stopped", "confirmed": True, "reason": "Operator test"}).status_code == 403
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.com"))
        user.role = "super_admin"
        db.commit()
    assert client.put("/api/settings/sending", json={"state": "stopped", "confirmed": True, "reason": "Emergency stop"}).status_code == 200

    assert post_inbound(client, "stopped-1").status_code == 202
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "stopped-1"))
        assert message.status == "Skipped"
        assert message.status_reason == "Global sending is stopped"


def test_configured_gateway_sends_once_snapshots_cost_and_accepts_dlr(sending_client, monkeypatch):
    client, app = sending_client
    rule = create_rule(client)
    assert rule.status_code == 201
    configured = client.patch("/api/settings", json={
        "billing": {"cost_per_segment_kes": "0.95", "currency": "KES"},
        "gateway": {"base_url": "https://gateway.example.com/send", "api_key": "fake-secret", "client_id": "fake-client", "access_key": "fake-access", "default_sender_id": "UPENFLOW", "allowed_sender_ids": ["UPENFLOW"]},
    })
    assert configured.status_code == 200
    sent = []

    class FakeAdapter:
        def __init__(self, base_url, api_key, client_id=None, access_key=None):
            assert base_url.startswith("https://gateway.example.com")
            assert api_key == "fake-secret"
            assert client_id == "fake-client"
            assert access_key == "fake-access"

        def send(self, sender_id, to, text, message_key, is_unicode=False):
            sent.append((sender_id, to, text, message_key))
            return "provider-1001"

    monkeypatch.setattr(rules, "ServiceBAdapter", FakeAdapter)
    response = post_inbound(client, "send-1001")
    assert response.status_code == 202
    assert post_inbound(client, "send-1001").json()["duplicate"] is True
    assert sent == [("UPENFLOW", "254712345678", "Order send-1001 dispatched", "send-1001")]
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "send-1001"))
        assert message.status == "Sent"
        assert message.cost_kes == Decimal("0.95")
        assert message.segments == 1
        assert message.attempts == 1

    dlr = post_dlr(client, "provider-1001", "delivered")
    assert dlr.status_code == 200
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "send-1001"))
        assert message.status == "Delivered"
        assert message.delivered_at is not None


def test_blocklist_and_duplicate_guard_stop_provider_calls(sending_client, monkeypatch):
    client, app = sending_client
    assert create_rule(client).status_code == 201
    assert client.patch("/api/settings", json={"gateway": {"base_url": "https://gateway.example.com/send", "api_key": "fake-secret", "client_id": "fake-client", "access_key": "fake-access", "default_sender_id": "UPENFLOW", "allowed_sender_ids": ["UPENFLOW"]}}).status_code == 200
    sent = []

    class FakeAdapter:
        def __init__(self, *args, **kwargs):
            pass

        def send(self, sender_id, to, text, message_key, is_unicode=False):
            sent.append(message_key)
            return f"provider-{message_key}"

    monkeypatch.setattr(rules, "ServiceBAdapter", FakeAdapter)
    blocked = client.post("/api/blocklist", json={"phone_number": "+254 711 111 111", "reason": "STOP reply"})
    assert blocked.status_code == 201
    assert post_inbound(client, "blocked-1", "0711111111").status_code == 202
    assert sent == []
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "blocked-1"))
        assert message.status == "Blocked"
    unblocked = client.delete(f"/api/blocklist/{blocked.json()['id']}")
    assert unblocked.status_code == 204
    assert post_inbound(client, "duplicate-1", order_ref="same-order").status_code == 202
    assert post_inbound(client, "duplicate-2", order_ref="same-order").status_code == 202
    assert sent == ["duplicate-1"]
    with app.state.session_factory() as db:
        duplicate = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "duplicate-2"))
        assert duplicate.status == "Blocked"
        assert duplicate.status_reason == "Duplicate message to this recipient"


def test_fake_test_mode_only_records_allowlisted_numbers(sending_client):
    client, app = sending_client
    assert create_rule(client).status_code == 201
    configured = client.patch("/api/settings", json={
        "gateway": {"base_url": "https://gateway.example.com/send", "api_key": "fake-secret", "client_id": "fake-client", "access_key": "fake-access", "default_sender_id": "UPENFLOW", "allowed_sender_ids": ["UPENFLOW"]},
        "safety": {"test_mode": True, "fake_gateway": True, "test_allowlist": ["0712345678"]},
    })
    assert configured.status_code == 200
    assert post_inbound(client, "test-allowed").status_code == 202
    timestamp = str(int(time.time()))
    payload = {"message_id": "test-denied", "recipient": "0711111111", "text": "Order dispatched", "order_ref": "test-denied"}
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(b"hmac-secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert client.post("/api/inbound/service-a", content=body, headers={"Content-Type": "application/json", "X-Service-A-Key": "api-key", "X-Service-A-Timestamp": timestamp, "X-Service-A-Signature": signature}).status_code == 202
    with app.state.session_factory() as db:
        allowed = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "test-allowed"))
        denied = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "test-denied"))
        assert allowed.status == "Sent"
        assert allowed.provider_message_id == "test-test-allowed"
        assert allowed.cost_kes == 0
        assert denied.status == "Blocked"
        assert denied.status_reason == "Recipient is not on the test-mode allowlist"