from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import AuditLog, SystemSetting, User, UserSession
from app.security import token_hash


@pytest.fixture
def settings_client(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'settings.db'}", otp_pepper="settings-pepper", cookie_secure=False))
    with TestClient(app) as client:
        with app.state.session_factory() as db:
            user = User(name="Admin", email="admin@example.com", password_hash="unused", role="super_admin")
            db.add(user)
            db.flush()
            db.add(UserSession(user_id=user.id, token_hash=token_hash("admin-token"), created_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc)))
            db.commit()
        client.cookies.set("upenflow_session", "admin-token")
        yield client, app


def test_gateway_key_is_encrypted_at_rest_and_never_returned(settings_client):
    client, app = settings_client
    secret = "gateway-test-secret-123"
    response = client.patch("/api/settings", json={
        "billing": {"cost_per_segment_kes": "0.95", "currency": "KES"},
        "gateway": {"base_url": "https://gateway.example.com/send", "api_key": secret, "default_sender_id": "UPENFLOW", "allowed_sender_ids": ["UPENFLOW"]},
        "limits": {"max_segments": 2},
    })

    assert response.status_code == 200
    assert response.json()["gateway"]["api_key"] == "••••••••"
    assert secret not in response.text
    assert client.get("/api/settings").json()["gateway"]["api_key"] == "••••••••"
    with app.state.session_factory() as db:
        record = db.scalar(select(SystemSetting).where(SystemSetting.key == "configuration"))
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "configuration_updated"))
        assert secret not in record.value["gateway"]["encrypted_api_key"]
        assert secret not in str(audit.after)


def test_configuration_is_super_admin_only(settings_client):
    client, app = settings_client
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.com"))
        user.role = "operator"
        db.commit()

    assert client.get("/api/settings").status_code == 403
    assert client.patch("/api/settings", json={"billing": {"cost_per_segment_kes": "1.25"}}).status_code == 403