from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth
from app.config import Settings
from app.main import create_app
from app.models import LoginChallenge, User
from app.security import hash_password, otp_hash


@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        otp_pepper="test-pepper",
        cookie_secure=False,
        first_admin_email="admin@example.com",
        first_admin_password="Strong-Password-9482!",
    )
    sent_codes = []
    monkeypatch.setattr(auth, "send_challenge_email", lambda settings, recipient, code: sent_codes.append(code))
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client, sent_codes, app


def login(client, email="admin@example.com", password="Strong-Password-9482!"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_registration_route_does_not_exist(client):
    test_client, _, _ = client
    assert test_client.post("/api/auth/register").status_code == 404


def test_password_alone_does_not_create_session_and_otp_is_single_use(client):
    test_client, codes, _ = client
    response = login(test_client)
    assert response.status_code == 200
    assert "upenflow_session" not in test_client.cookies
    assert test_client.get("/api/auth/me").status_code == 401

    verified = test_client.post("/api/auth/verify-otp", json={"code": codes[-1]})
    assert verified.status_code == 200
    assert test_client.get("/api/auth/me").status_code == 200
    test_client.post("/api/auth/logout")
    assert test_client.post("/api/auth/verify-otp", json={"code": codes[-1]}).status_code == 401


def test_expired_otp_is_rejected(client):
    test_client, codes, app = client
    assert login(test_client).status_code == 200
    with app.state.session_factory() as db:
        challenge = db.scalar(select(LoginChallenge))
        challenge.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert test_client.post("/api/auth/verify-otp", json={"code": codes[-1]}).status_code == 401


def test_fifth_bad_password_locks_account_for_fifteen_minutes(client):
    test_client, _, app = client
    for _ in range(5):
        response = login(test_client, password="incorrect-password")
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.com"))
        assert user.locked_until is not None
        remaining = user.locked_until - datetime.now(timezone.utc).replace(tzinfo=None)
        assert timedelta(minutes=14, seconds=59) < remaining <= timedelta(minutes=15)
    assert login(test_client).status_code == 401


def test_deactivated_user_cannot_request_otp(client):
    test_client, _, app = client
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.email == "admin@example.com"))
        user.is_active = False
        db.commit()
    response = login(test_client)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_resend_limit_is_three(client):
    test_client, codes, app = client
    test_client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Strong-Password-9482!"})
    with app.state.session_factory() as db:
        challenge = db.scalar(select(LoginChallenge))
        challenge.last_sent_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        db.commit()
    for resend_number in range(1, 4):
        response = test_client.post("/api/auth/resend-otp")
        assert response.status_code == 200
        with app.state.session_factory() as db:
            challenge = db.scalar(select(LoginChallenge))
            challenge.last_sent_at = datetime.now(timezone.utc) - timedelta(minutes=2)
            db.commit()
    assert len(codes) == 4
    assert test_client.post("/api/auth/resend-otp").status_code == 429