import logging
import secrets
import smtplib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.email import send_account_email, send_otp_email
from app.models import AuditLog, AuthRateLimit, LoginChallenge, User, UserSession
from app.security import hash_password, otp_hash, otp_matches, random_otp, token_hash, verify_password

logger = logging.getLogger("upenflow.auth")


def add_login_audit(db: Session, request: Request, actor_id: int | None, action: str, entity_id: str) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity="session",
            entity_id=entity_id,
            ip_address=request.client.host if request.client else None,
            created_at=datetime.now(timezone.utc),
        )
    )


router = APIRouter(prefix="/api/auth", tags=["authentication"])
SESSION_COOKIE = "upenflow_session"
CHALLENGE_COOKIE = "upenflow_otp_challenge"
GENERIC_LOGIN_ERROR = "Invalid email or password"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class VerifyOtpRequest(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def settings_for(request: Request) -> Settings:
    return request.app.state.settings


def enforce_rate_limit(db: Session, request: Request, identity: str, settings: Settings, include_email: bool = True) -> None:
    now = utc_now()
    window = timedelta(seconds=settings.auth_rate_limit_window_seconds)
    scopes = [(f"ip:{request.client.host if request.client else 'unknown'}", settings.auth_rate_limit_ip_attempts)]
    if include_email:
        scopes.append((f"email:{identity.strip().lower()}", settings.auth_rate_limit_email_attempts))
    for key, limit in scopes:
        bucket_key = token_hash(key)
        bucket = db.scalar(select(AuthRateLimit).where(AuthRateLimit.bucket_hash == bucket_key))
        if bucket is None:
            bucket = AuthRateLimit(bucket_hash=bucket_key, window_started_at=now, attempts=0)
            db.add(bucket)
            db.flush()
        elif now - aware(bucket.window_started_at) >= window:
            bucket.window_started_at = now
            bucket.attempts = 0
        if bucket.attempts >= limit:
            db.commit()
            raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
        bucket.attempts += 1
    db.commit()


def send_challenge_email(settings: Settings, recipient: str, code: str) -> None:
    send_otp_email(settings, recipient, code)


def issue_challenge(db: Session, user: User, settings: Settings, now: datetime) -> tuple[LoginChallenge, str, str]:
    challenge_token = secrets.token_urlsafe(32)
    code = random_otp()
    challenge = LoginChallenge(
        user_id=user.id,
        challenge_hash=token_hash(challenge_token),
        code_hash=otp_hash(code, settings.otp_pepper),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.otp_validity_seconds),
        last_sent_at=now,
    )
    db.add(challenge)
    db.flush()
    return challenge, challenge_token, code


def set_cookie(response: Response, key: str, value: str, settings: Settings, max_age: int) -> None:
    response.set_cookie(
        key,
        value,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = settings_for(request)
    enforce_rate_limit(db, request, payload.email, settings)
    now = utc_now()
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not user.is_active or not user.password_set:
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)

    locked_until = aware(user.locked_until) if user.locked_until else None
    if locked_until and locked_until > now:
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)
    if not verify_password(user.password_hash, payload.password):
        window_start = aware(user.failed_window_started_at) if user.failed_window_started_at else None
        if window_start is None or now - window_start >= timedelta(minutes=15):
            user.failed_window_started_at = now
            user.failed_password_attempts = 0
        user.failed_password_attempts += 1
        if user.failed_password_attempts >= 5:
            user.locked_until = now + timedelta(minutes=15)
            try:
                send_account_email(
                    settings,
                    user.email,
                    "Your Upenflow Notify account is temporarily locked",
                    "We detected five unsuccessful sign-in attempts. Your account is locked for 15 minutes. If this was not you, contact your Super Admin.",
                )
            except (OSError, RuntimeError, smtplib.SMTPException):
                logger.warning("lockout_email_failed", extra={"fields": {"user_id": user.id}})
            add_login_audit(db, request, user.id, "account_locked", str(user.id))
        add_login_audit(db, request, user.id, "login_failed", str(user.id))
        db.commit()
        raise HTTPException(status_code=401, detail=GENERIC_LOGIN_ERROR)

    user.failed_password_attempts = 0
    user.failed_window_started_at = None
    user.locked_until = None
    challenge, challenge_token, code = issue_challenge(db, user, settings, now)
    try:
        send_challenge_email(settings, user.email, code)
    except (OSError, RuntimeError, smtplib.SMTPException) as error:
        db.rollback()
        raise HTTPException(status_code=503, detail="Unable to send verification code") from error
    db.commit()
    set_cookie(response, CHALLENGE_COOKIE, challenge_token, settings, settings.otp_validity_seconds)
    return {"message": "Verification code sent", "expires_in": settings.otp_validity_seconds}


@router.post("/resend-otp")
def resend_otp(request: Request, response: Response, db: Session = Depends(get_db)):
    settings = settings_for(request)
    raw_token = request.cookies.get(CHALLENGE_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Verification attempt expired")
    challenge = db.scalar(select(LoginChallenge).where(LoginChallenge.challenge_hash == token_hash(raw_token)))
    challenge_user = db.get(User, challenge.user_id) if challenge else None
    enforce_rate_limit(db, request, challenge_user.email if challenge_user else "invalid-challenge", settings, include_email=challenge_user is not None)
    now = utc_now()
    if not challenge or challenge.used_at or aware(challenge.expires_at) <= now:
        raise HTTPException(status_code=401, detail="Verification attempt expired")
    if challenge.resends >= 3:
        raise HTTPException(status_code=429, detail="Resend limit reached")
    if now - aware(challenge.last_sent_at) < timedelta(seconds=settings.otp_resend_seconds):
        raise HTTPException(status_code=429, detail="Please wait before requesting another code")

    user = db.get(User, challenge.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Verification attempt expired")
    code = random_otp()
    challenge.code_hash = otp_hash(code, settings.otp_pepper)
    challenge.expires_at = now + timedelta(seconds=settings.otp_validity_seconds)
    challenge.last_sent_at = now
    challenge.resends += 1
    challenge.attempts = 0
    try:
        send_challenge_email(settings, user.email, code)
    except (OSError, RuntimeError, smtplib.SMTPException) as error:
        db.rollback()
        raise HTTPException(status_code=503, detail="Unable to send verification code") from error
    db.commit()
    return {"message": "Verification code sent", "expires_in": settings.otp_validity_seconds}


@router.post("/verify-otp")
def verify_otp(payload: VerifyOtpRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = settings_for(request)
    raw_token = request.cookies.get(CHALLENGE_COOKIE)
    challenge = db.scalar(
        select(LoginChallenge).where(LoginChallenge.challenge_hash == token_hash(raw_token or ""))
    )
    challenge_user = db.get(User, challenge.user_id) if challenge else None
    enforce_rate_limit(db, request, challenge_user.email if challenge_user else "invalid-challenge", settings, include_email=challenge_user is not None)
    now = utc_now()
    if not challenge or challenge.used_at or aware(challenge.expires_at) <= now:
        raise HTTPException(status_code=401, detail="Invalid or expired verification code")
    user = db.get(User, challenge.user_id)
    if not user or not user.is_active:
        challenge.used_at = now
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid or expired verification code")
    if not otp_matches(payload.code, challenge.code_hash, settings.otp_pepper):
        challenge.attempts += 1
        if challenge.attempts >= 5:
            challenge.used_at = now
        add_login_audit(db, request, user.id, "otp_failed", str(user.id))
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid or expired verification code")

    claimed = db.execute(
        update(LoginChallenge)
        .where(LoginChallenge.id == challenge.id, LoginChallenge.used_at.is_(None))
        .values(used_at=now)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=401, detail="Invalid or expired verification code")
    session_token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=token_hash(session_token),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            created_at=now,
            last_seen_at=now,
        )
    )
    add_login_audit(db, request, user.id, "login_succeeded", str(user.id))
    db.commit()
    response.delete_cookie(CHALLENGE_COOKIE, path="/")
    set_cookie(response, SESSION_COOKIE, session_token, settings, settings.session_absolute_seconds)
    return {"message": "Signed in", "user": {"name": user.name, "email": user.email, "role": user.role}}


def current_user(request: Request, db: Session) -> tuple[User, UserSession]:
    raw_token = request.cookies.get(SESSION_COOKIE)
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(raw_token or "")))
    now = utc_now()
    if not session or session.revoked_at:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if now - aware(session.last_seen_at) >= timedelta(seconds=request.app.state.settings.session_idle_seconds):
        session.revoked_at = now
        db.commit()
        raise HTTPException(status_code=401, detail="Session expired")
    if now - aware(session.created_at) >= timedelta(seconds=request.app.state.settings.session_absolute_seconds):
        session.revoked_at = now
        db.commit()
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        session.revoked_at = now
        db.commit()
        raise HTTPException(status_code=401, detail="Not authenticated")
    session.last_seen_at = now
    db.commit()
    return user, session


def get_authenticated_user(request: Request, db: Session = Depends(get_db)) -> User:
    user, _ = current_user(request, db)
    return user


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    user, _ = current_user(request, db)
    return {"name": user.name, "email": user.email, "role": user.role}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw_token = request.cookies.get(SESSION_COOKIE)
    if raw_token:
        session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash(raw_token)))
        if session and not session.revoked_at:
            session.revoked_at = utc_now()
            add_login_audit(db, request, session.user_id, "logout", str(session.user_id))
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(request: Request, response: Response, db: Session = Depends(get_db)):
    user, _ = current_user(request, db)
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )
    add_login_audit(db, request, user.id, "logout_all", str(user.id))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")