import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import current_user, enforce_rate_limit, get_authenticated_user
from app.database import get_db
from app.email import send_account_email
from app.models import AccountToken, AuditLog, User, UserSession
from app.security import hash_password, otp_hash, otp_matches, random_otp, token_hash, valid_password, verify_password


router = APIRouter(tags=["accounts"])


class CreateUserRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    role: Literal["super_admin", "operator", "viewer"]


class UpdateUserRequest(BaseModel):
    role: Literal["super_admin", "operator", "viewer"] | None = None
    is_active: bool | None = None


class UpdateProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class PasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    new_password: str = Field(min_length=12, max_length=1024)
    confirm_password: str

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        if not valid_password(self.new_password):
            raise ValueError("Use at least 12 characters with letters and numbers and avoid common passwords")
        return self


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)
    confirm_password: str

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        if not valid_password(self.new_password):
            raise ValueError("Use at least 12 characters with letters and numbers and avoid common passwords")
        return self


class ConfirmPasswordChangeRequest(BaseModel):
    challenge_token: str = Field(min_length=20, max_length=200)
    code: str = Field(pattern=r"^\d{6}$")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def require_super_admin(user: User = Depends(get_authenticated_user)) -> User:
    if user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin access required")
    return user


def add_audit(db: Session, actor: User, action: str, entity: str, entity_id: str, before: dict | None, after: dict | None, request: Request):
    db.add(
        AuditLog(
            actor_id=actor.id,
            action=action,
            entity=entity,
            entity_id=entity_id,
            before=before,
            after=after,
            ip_address=request.client.host if request.client else None,
            created_at=now_utc(),
        )
    )


def create_account_token(db: Session, user: User, purpose: str, validity: timedelta) -> str:
    raw_token = secrets.token_urlsafe(36)
    db.add(
        AccountToken(
            user_id=user.id,
            token_hash=token_hash(raw_token),
            purpose=purpose,
            created_at=now_utc(),
            expires_at=now_utc() + validity,
        )
    )
    return raw_token


def send_account_link(request: Request, user: User, raw_token: str, purpose: str, validity: str) -> None:
    settings = request.app.state.settings
    link = f"{settings.frontend_base_url.rstrip('/')}/set-password?token={raw_token}"
    send_account_email(
        settings,
        user.email,
        "Set your Upenflow Notify password" if purpose == "invite" else "Reset your Upenflow Notify password",
        f"Use this one-time link within {validity} to set your password:\n\n{link}",
    )


def user_view(user: User) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "is_active": user.is_active, "password_set": user.password_set}


@router.get("/api/me")
def get_profile(user: User = Depends(get_authenticated_user)):
    return {"name": user.name, "email": user.email, "role": user.role}


@router.patch("/api/me")
def update_profile(payload: UpdateProfileRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    previous_name = user.name
    user.name = payload.name
    add_audit(db, user, "profile_updated", "user", str(user.id), {"name": previous_name}, {"name": user.name}, request)
    db.commit()
    return {"name": user.name, "email": user.email, "role": user.role}


@router.get("/api/me/sessions")
def list_my_sessions(request: Request, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    raw_token = request.cookies.get("upenflow_session", "")
    current_hash = token_hash(raw_token)
    sessions = db.scalars(
        select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)).order_by(UserSession.last_seen_at.desc())
    ).all()
    return [
        {
            "id": session.id,
            "device": session.user_agent or "Unknown device",
            "ip_address": session.ip_address,
            "last_seen_at": session.last_seen_at,
            "current": session.token_hash == current_hash,
        }
        for session in sessions
    ]


@router.delete("/api/me/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_session(session_id: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    session = db.get(UserSession, session_id)
    if not session or session.user_id != user.id or session.revoked_at:
        raise HTTPException(status_code=404, detail="Session not found")
    session.revoked_at = now_utc()
    db.commit()


@router.post("/api/me/password/change/request-otp")
def request_password_change_otp(payload: ChangePasswordRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    settings = request.app.state.settings
    raw_token = secrets.token_urlsafe(36)
    code = random_otp()
    db.add(
        AccountToken(
            user_id=user.id,
            token_hash=token_hash(raw_token),
            purpose="password_change",
            code_hash=otp_hash(code, settings.otp_pepper),
            pending_password_hash=hash_password(payload.new_password),
            attempts=0,
            created_at=now_utc(),
            expires_at=now_utc() + timedelta(minutes=5),
        )
    )
    try:
        send_account_email(
            settings,
            user.email,
            "Confirm your password change",
            f"Use this confirmation code to change your password: {code}",
        )
    except (OSError, RuntimeError) as error:
        db.rollback()
        raise HTTPException(status_code=503, detail="Unable to send confirmation code") from error
    db.commit()
    return {"message": "Confirmation code sent", "challenge_token": raw_token, "expires_in": 300}


@router.post("/api/me/password/change/confirm")
def confirm_password_change(payload: ConfirmPasswordChangeRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    challenge = db.scalar(select(AccountToken).where(AccountToken.token_hash == token_hash(payload.challenge_token)))
    now = now_utc()
    if (
        not challenge
        or challenge.user_id != user.id
        or challenge.purpose != "password_change"
        or challenge.used_at
        or as_utc(challenge.expires_at) <= now
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired confirmation code")
    if not otp_matches(payload.code, challenge.code_hash or "", request.app.state.settings.otp_pepper):
        challenge.attempts += 1
        if challenge.attempts >= 5:
            challenge.used_at = now
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired confirmation code")
    if not challenge.pending_password_hash:
        raise HTTPException(status_code=400, detail="Invalid or expired confirmation code")
    challenge.used_at = now
    user.password_hash = challenge.pending_password_hash
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None), UserSession.token_hash != token_hash(request.cookies.get("upenflow_session", "")))
        .values(revoked_at=now)
    )
    add_audit(db, user, "password_changed", "user", str(user.id), None, None, request)
    db.commit()
    return {"message": "Password changed"}


@router.get("/api/admin/users")
def list_users(db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    return [user_view(user) for user in db.scalars(select(User).order_by(User.email)).all()]


@router.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
def create_user(payload: CreateUserRequest, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    email = str(payload.email).lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="A user with that email already exists")
    user = User(
        name=payload.name,
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        password_set=False,
        role=payload.role,
        is_active=True,
        created_by=admin.id,
    )
    db.add(user)
    db.flush()
    raw_token = create_account_token(db, user, "invite", timedelta(hours=24))
    try:
        send_account_link(request, user, raw_token, "invite", "24 hours")
    except (OSError, RuntimeError) as error:
        db.rollback()
        raise HTTPException(status_code=503, detail="Unable to send invitation") from error
    add_audit(db, admin, "user_invited", "user", str(user.id), None, {"email": user.email, "role": user.role}, request)
    db.commit()
    return user_view(user)


@router.post("/api/admin/users/{user_id}/resend-invite")
def resend_invite(user_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    user = db.get(User, user_id)
    if not user or user.password_set:
        raise HTTPException(status_code=404, detail="Pending invitation not found")
    now = now_utc()
    db.execute(
        update(AccountToken)
        .where(AccountToken.user_id == user.id, AccountToken.purpose == "invite", AccountToken.used_at.is_(None))
        .values(used_at=now)
    )
    raw_token = create_account_token(db, user, "invite", timedelta(hours=24))
    try:
        send_account_link(request, user, raw_token, "invite", "24 hours")
    except (OSError, RuntimeError) as error:
        db.rollback()
        raise HTTPException(status_code=503, detail="Unable to send invitation") from error
    db.commit()
    return {"message": "Invitation sent"}


@router.patch("/api/admin/users/{user_id}")
def update_user(user_id: int, payload: UpdateUserRequest, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return user_view(user)
    if user.id == admin.id and changes.get("is_active") is False:
        raise HTTPException(status_code=409, detail="You cannot deactivate your own account")
    will_remove_admin = user.is_active and user.role == "super_admin" and (
        changes.get("is_active") is False or changes.get("role", user.role) != "super_admin"
    )
    if will_remove_admin:
        active_admins = db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True), User.role == "super_admin"))
        if active_admins <= 1:
            raise HTTPException(status_code=409, detail="The last active Super Admin cannot be deactivated or demoted")
    before = {"role": user.role, "is_active": user.is_active}
    for key, value in changes.items():
        setattr(user, key, value)
    if changes.get("is_active") is False:
        db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now_utc())
        )
    add_audit(db, admin, "user_updated", "user", str(user.id), before, {"role": user.role, "is_active": user.is_active}, request)
    db.commit()
    return user_view(user)


@router.post("/api/admin/users/{user_id}/force-password-reset")
def force_password_reset(user_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="Active user not found")
    raw_token = create_account_token(db, user, "reset", timedelta(minutes=30))
    try:
        send_account_link(request, user, raw_token, "reset", "30 minutes")
    except (OSError, RuntimeError) as error:
        db.rollback()
        raise HTTPException(status_code=503, detail="Unable to send password reset") from error
    db.commit()
    return {"message": "Password reset link sent"}


@router.post("/api/auth/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    enforce_rate_limit(db, request, payload.email, request.app.state.settings)
    user = db.scalar(select(User).where(User.email == str(payload.email).lower(), User.is_active.is_(True)))
    if user:
        raw_token = create_account_token(db, user, "reset", timedelta(minutes=30))
        try:
            send_account_link(request, user, raw_token, "reset", "30 minutes")
        except (OSError, RuntimeError):
            db.rollback()
            return {"message": "If the account exists, password reset instructions have been sent"}
        db.commit()
    return {"message": "If the account exists, password reset instructions have been sent"}


@router.post("/api/auth/set-password")
def set_password(payload: PasswordRequest, request: Request, db: Session = Depends(get_db)):
    account_token = db.scalar(select(AccountToken).where(AccountToken.token_hash == token_hash(payload.token)))
    now = now_utc()
    if not account_token or account_token.used_at or as_utc(account_token.expires_at) <= now:
        raise HTTPException(status_code=400, detail="Password link is invalid or expired")
    user = db.get(User, account_token.user_id)
    if not user or not user.is_active:
        account_token.used_at = now
        db.commit()
        raise HTTPException(status_code=400, detail="Password link is invalid or expired")
    account_token.used_at = now
    user.password_hash = hash_password(payload.new_password)
    user.password_set = True
    if account_token.purpose == "reset":
        db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
    add_audit(db, user, "password_set", "user", str(user.id), None, {"purpose": account_token.purpose}, request)
    db.commit()
    return {"message": "Password updated"}


@router.post("/api/admin/users/{user_id}/revoke-sessions", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_sessions(user_id: int, request: Request, db: Session = Depends(get_db), admin: User = Depends(require_super_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now_utc())
    )
    add_audit(db, admin, "sessions_revoked", "user", str(user.id), None, None, request)
    db.commit()