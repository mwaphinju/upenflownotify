import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import InboundMessage, MappingRuleVersion, User, UserSession
from app.security import token_hash


@pytest.fixture
def rule_client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'rules.db'}",
        otp_pepper="test-pepper",
        cookie_secure=False,
        service_a_api_key="test-api-key",
        service_a_hmac_secret="test-hmac-secret",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        with app.state.session_factory() as db:
            user = User(
                name="Rule Admin",
                email="rules@example.com",
                password_hash="unused",
                role="super_admin",
            )
            db.add(user)
            db.flush()
            db.add(
                UserSession(
                    user_id=user.id,
                    token_hash=token_hash("test-session-token"),
                    created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                    last_seen_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                )
            )
            db.commit()
        client.cookies.set("upenflow_session", "test-session-token")
        yield client, app


def rule_data(**overrides):
    return {
        "name": "Order dispatched",
        "priority": 10,
        "match_type": "contains",
        "match_value": "order",
        "case_sensitive": False,
        "sender_id": "UPENFLOW",
        "outbound_template": "Hello {{recipient}}, order {{order_ref}}: {{original_text}}",
        "is_enabled": True,
        **overrides,
    }


def signed_webhook(client, payload, timestamp=None):
    timestamp = str(timestamp or int(time.time()))
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(
        b"test-hmac-secret",
        timestamp.encode() + b"." + body,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/api/inbound/service-a",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Service-A-Key": "test-api-key",
            "X-Service-A-Timestamp": timestamp,
            "X-Service-A-Signature": signature,
        },
    )


def test_first_matching_priority_wins(rule_client):
    client, _ = rule_client
    client.post("/api/rules", json=rule_data(name="Later", priority=20, match_value="dispatched"))
    client.post("/api/rules", json=rule_data(name="First", priority=10))

    result = client.post("/api/rules/test", json={"text": "Order dispatched", "order_ref": "A-42"})

    assert result.status_code == 200
    assert result.json()["rule"]["name"] == "First"
    assert result.json()["rendered_text"] == "Hello 254700000000, order A-42: Order dispatched"


def test_invalid_regex_and_unavailable_template_placeholder_are_rejected(rule_client):
    client, _ = rule_client
    invalid_regex = client.post("/api/rules", json=rule_data(match_type="regex", match_value="["))
    unknown_placeholder = client.post("/api/rules", json=rule_data(outbound_template="Hi {{missing}}"))

    assert invalid_regex.status_code == 422
    assert unknown_placeholder.status_code == 422


def test_viewer_cannot_edit_rules(rule_client):
    client, app = rule_client
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "rules@example.com"))
        user.role = "viewer"
        db.commit()

    response = client.post("/api/rules", json=rule_data())

    assert response.status_code == 403


def test_webhook_replay_is_idempotent_and_old_message_keeps_rule_version(rule_client):
    client, app = rule_client
    created = client.post("/api/rules", json=rule_data(match_type="regex", match_value=r"Order (?P<order_no>\d+) dispatched", outbound_template="Order {{order_no}} dispatched"))
    assert created.status_code == 201
    payload = {
        "message_id": "service-a-1001",
        "recipient": "0712345678",
        "text": "Order 42 dispatched",
        "order_ref": "A-42",
    }

    first = signed_webhook(client, payload)
    duplicate = signed_webhook(client, payload)

    assert first.status_code == 202
    assert first.json()["duplicate"] is False
    assert duplicate.status_code == 202
    assert duplicate.json()["duplicate"] is True
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "service-a-1001"))
        old_version_id = message.rule_version_id
        assert message.status == "Queued"
        assert message.rendered_text == "Order 42 dispatched"
        assert db.scalar(select(func.count()).select_from(InboundMessage)) == 1
    updated = client.patch(f"/api/rules/{created.json()['id']}", json={"outbound_template": "Updated {{order_no}}"})
    assert updated.status_code == 200
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "service-a-1001"))
        assert message.rule_version_id == old_version_id
        assert db.scalar(select(func.count()).select_from(MappingRuleVersion)) == 2


def test_webhook_rejects_bad_signature_and_stale_timestamp(rule_client):
    client, _ = rule_client
    payload = {"message_id": "bad-auth", "recipient": "0712345678", "text": "Delivered"}
    stale = signed_webhook(client, payload, int(time.time()) - 301)
    invalid_signature = client.post(
        "/api/inbound/service-a",
        json=payload,
        headers={
            "X-Service-A-Key": "test-api-key",
            "X-Service-A-Timestamp": str(int(time.time())),
            "X-Service-A-Signature": "0" * 64,
        },
    )
    assert stale.status_code == 401
    assert invalid_signature.status_code == 401