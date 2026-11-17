from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import get_authenticated_user
from app.database import get_db
from app.models import AuditLog, InboundMessage, SystemSetting, User


router = APIRouter(prefix="/api/settings", tags=["sending"])


class SendingUpdate(BaseModel):
    state: Literal["on", "paused", "stopped"]
    confirmed: bool
    reason: str = Field(min_length=3, max_length=255)
    resume_policy: Literal["send_all", "discard_all", "send_recent"] | None = None
    stale_minutes: int = Field(default=60, ge=1, le=10080)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/sending")
def get_sending(db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "sending"))
    state = setting.value["state"] if setting else "on"
    configuration = db.scalar(select(SystemSetting).where(SystemSetting.key == "configuration"))
    test_mode = configuration.value.get("safety", {}).get("test_mode", False) if configuration else False
    queued = db.scalar(select(func.count()).select_from(InboundMessage).where(InboundMessage.status == "Queued"))
    return {"state": state, "queued_count": queued or 0, "test_mode": test_mode}


@router.put("/sending")
def update_sending(payload: SendingUpdate, request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    if user.role != "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin access required")
    if not payload.confirmed:
        raise HTTPException(status_code=422, detail="Confirm the sending-state change")
    setting = db.scalar(select(SystemSetting).where(SystemSetting.key == "sending"))
    old_state = setting.value["state"] if setting else "on"
    if old_state == payload.state:
        raise HTTPException(status_code=409, detail="Sending is already in that state")
    now = now_utc()
    queued_count = db.scalar(select(func.count()).select_from(InboundMessage).where(InboundMessage.status == "Queued")) or 0
    if old_state == "paused" and payload.state == "on":
        if payload.resume_policy is None:
            raise HTTPException(status_code=422, detail="Choose how to handle queued messages before resuming")
        if payload.resume_policy == "discard_all":
            db.execute(
                update(InboundMessage)
                .where(InboundMessage.status == "Queued")
                .values(status="Skipped", status_reason="Discarded when sending resumed")
            )
        elif payload.resume_policy == "send_recent":
            cutoff = now - timedelta(minutes=payload.stale_minutes)
            db.execute(
                update(InboundMessage)
                .where(InboundMessage.status == "Queued", InboundMessage.received_at < cutoff)
                .values(status="Skipped", status_reason="Message exceeded the resume age limit")
            )
    elif payload.state == "stopped":
        db.execute(
            update(InboundMessage)
            .where(InboundMessage.status == "Queued")
            .values(status="Skipped", status_reason="Global sending was stopped")
        )

    after = {"state": payload.state}
    if setting:
        setting.value = after
        setting.updated_by = user.id
        setting.updated_at = now
    else:
        db.add(SystemSetting(key="sending", value=after, updated_by=user.id, updated_at=now))
    db.add(
        AuditLog(
            actor_id=user.id,
            action="sending_state_changed",
            entity="setting",
            entity_id="sending",
            before={"state": old_state},
            after=after,
            reason=payload.reason,
            ip_address=request.client.host if request.client else None,
            created_at=now,
        )
    )
    db.commit()
    if old_state == "paused" and payload.state == "on" and payload.resume_policy != "discard_all":
        from app.rules import enqueue_delivery

        queued_ids = db.scalars(select(InboundMessage.id).where(InboundMessage.status == "Queued")).all()
        for message_id in queued_ids:
            enqueue_delivery(request, background_tasks, message_id)
    remaining = db.scalar(select(func.count()).select_from(InboundMessage).where(InboundMessage.status == "Queued")) or 0
    configuration = db.scalar(select(SystemSetting).where(SystemSetting.key == "configuration"))
    test_mode = configuration.value.get("safety", {}).get("test_mode", False) if configuration else False
    return {"state": payload.state, "queued_count": remaining, "affected_queued_count": queued_count, "test_mode": test_mode}