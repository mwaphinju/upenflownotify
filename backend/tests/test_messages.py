import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import InboundMessage, User, UserSession
from app.phone import normalize_kenyan_mobile
from app.security import token_hash


@pytest.fixture
def messages_client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'messages.db'}", otp_pepper="messages-pepper", cookie_secure=False, service_a_api_key="api-key", service_a_hmac_secret="hmac-secret")
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


def send_message(client, message_id, recipient):
    timestamp = str(int(time.time()))
    body = json.dumps({"message_id": message_id, "recipient": recipient, "text": "Order delivered", "order_ref": message_id}, separators=(",", ":")).encode()
    signature = hmac.new(b"hmac-secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return client.post("/api/inbound/service-a", content=body, headers={"Content-Type": "application/json", "X-Service-A-Key": "api-key", "X-Service-A-Timestamp": timestamp, "X-Service-A-Signature": signature})


@pytest.mark.parametrize(("source", "expected"), [
    ("0712 345 678", "254712345678"),
    ("712345678", "254712345678"),
    ("+254 110 123 456", "254110123456"),
    ("0110-123-456", "254110123456"),
    ("0201234567", None),
    ("+255712345678", None),
])
def test_kenyan_mobile_normalization(source, expected):
    assert normalize_kenyan_mobile(source) == expected


def test_phone_search_matches_local_and_international_formats_and_masks_viewer(messages_client):
    client, app = messages_client
    assert send_message(client, "search-1", "0712345678").status_code == 202
    assert send_message(client, "search-2", "+254712345678").status_code == 202

    local_search = client.get("/api/messages", params={"search": "0712345678"}).json()
    international_search = client.get("/api/messages", params={"search": "+254712345678"}).json()
    assert local_search["total"] == international_search["total"] == 2
    assert all(row["recipient"] == "254712345678" for row in local_search["items"])

    with app.state.session_factory() as db:
        admin = db.scalar(select(User).where(User.email == "admin@example.com"))
        admin.role = "viewer"
        db.commit()
    masked = client.get("/api/messages").json()["items"][0]["recipient"]
    assert masked == "2547***678"
    assert client.get("/api/messages/export.csv").status_code == 403


def test_invalid_landline_is_logged_and_dashboard_counts_it(messages_client):
    client, app = messages_client
    assert send_message(client, "landline-1", "0201234567").status_code == 202
    with app.state.session_factory() as db:
        message = db.scalar(select(InboundMessage).where(InboundMessage.source_message_id == "landline-1"))
        assert message.status == "Invalid recipient"
    dashboard = client.get("/api/dashboard", params={"period": "daily"}).json()
    assert dashboard["kpis"]["received"]["value"] == 1
    assert dashboard["kpis"]["sent"]["value"] == 0