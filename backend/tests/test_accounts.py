import re
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import accounts, auth
from app.config import Settings
from app.main import create_app
from app.models import User, UserSession
from app.security import token_hash


@pytest.fixture
def account_client(tmp_path, monkeypatch):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'accounts.db'}",
        otp_pepper="account-test-pepper",
        cookie_secure=False,
        first_admin_email="admin@example.com",
        first_admin_password="Strong-Password-9482!",
    )
    sent_emails = []
    sent_codes = []
    monkeypatch.setattr(accounts, "send_account_email", lambda settings, recipient, subject, content: sent_emails.append((recipient, subject, content)))
    monkeypatch.setattr(auth, "send_challenge_email", lambda settings, recipient, code: sent_codes.append(code))
    app = create_app(settings)
    with TestClient(app) as client:
        with app.state.session_factory() as db:
            admin = db.scalar(select(User).where(User.email == "admin@example.com"))
            db.add(
                UserSession(
                    user_id=admin.id,
                    token_hash=token_hash("admin-session"),
                    ip_address="127.0.0.1",
                    user_agent="Test Browser",
                    created_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        client.cookies.set("upenflow_session", "admin-session")
        yield client, app, sent_emails, sent_codes


def test_admin_invite_sets_password_once_and_allows_otp_login(account_client):
    client, _, sent_emails, sent_codes = account_client
    invited = client.post(
        "/api/admin/users",
        json={"name": "New Operator", "email": "operator@example.com", "role": "operator"},
    )
    assert invited.status_code == 201
    assert invited.json()["password_set"] is False
    token = re.search(r"token=([A-Za-z0-9_-]+)", sent_emails[-1][2]).group(1)
    password = "A quiet river flows 9281!"
    set_password = client.post(
        "/api/auth/set-password",
        json={"token": token, "new_password": password, "confirm_password": password},
    )
    assert set_password.status_code == 200
    assert client.post(
        "/api/auth/set-password",
        json={"token": token, "new_password": password, "confirm_password": password},
    ).status_code == 400

    client.cookies.clear()
    login = client.post("/api/auth/login", json={"email": "operator@example.com", "password": password})
    assert login.status_code == 200
    assert client.post("/api/auth/verify-otp", json={"code": sent_codes[-1]}).status_code == 200


def test_viewer_cannot_manage_users_and_last_admin_cannot_deactivate_self(account_client):
    client, app, _, _ = account_client
    with app.state.session_factory() as db:
        admin = db.scalar(select(User).where(User.email == "admin@example.com"))
        admin.role = "viewer"
        db.commit()
    denied = client.get("/api/admin/users")
    assert denied.status_code == 403

    with app.state.session_factory() as db:
        admin = db.scalar(select(User).where(User.email == "admin@example.com"))
        admin.role = "super_admin"
        db.commit()
    protected = client.patch("/api/admin/users/1", json={"is_active": False})
    assert protected.status_code == 409


def test_revoking_current_session_returns_401_on_next_request(account_client):
    client, _, _, _ = account_client
    sessions = client.get("/api/me/sessions")
    assert sessions.status_code == 200
    current = next(session for session in sessions.json() if session["current"])

    revoked = client.delete(f"/api/me/sessions/{current['id']}")

    assert revoked.status_code == 204
    assert client.get("/api/me").status_code == 401


def test_password_change_requires_email_otp_and_revokes_other_sessions(account_client):
    client, _, sent_emails, _ = account_client
    requested = client.post(
        "/api/me/password/change/request-otp",
        json={
            "current_password": "Strong-Password-9482!",
            "new_password": "A quiet river flows 9281!",
            "confirm_password": "A quiet river flows 9281!",
        },
    )
    assert requested.status_code == 200
    code = re.search(r"code to change your password: (\d{6})", sent_emails[-1][2]).group(1)
    challenge = requested.json()["challenge_token"]

    confirmed = client.post("/api/me/password/change/confirm", json={"challenge_token": challenge, "code": code})

    assert confirmed.status_code == 200
    assert client.get("/api/me").status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "admin@example.com", "password": "A quiet river flows 9281!"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Strong-Password-9482!"}).status_code == 401


def test_forgot_password_is_generic_and_reset_revokes_sessions(account_client):
    client, _, sent_emails, _ = account_client
    unknown = client.post("/api/auth/forgot-password", json={"email": "missing@example.com"})
    known = client.post("/api/auth/forgot-password", json={"email": "admin@example.com"})
    assert unknown.json() == known.json()
    token = re.search(r"token=([A-Za-z0-9_-]+)", sent_emails[-1][2]).group(1)
    password = "A quiet river flows 9281!"

    reset = client.post("/api/auth/set-password", json={"token": token, "new_password": password, "confirm_password": password})

    assert reset.status_code == 200
    assert client.get("/api/me").status_code == 401


def test_authentication_is_rate_limited_per_email(account_client):
    client, app, _, _ = account_client
    app.state.settings.auth_rate_limit_email_attempts = 2
    for _ in range(2):
        assert client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong-password"}).status_code == 401

    limited = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong-password"})

    assert limited.status_code == 429