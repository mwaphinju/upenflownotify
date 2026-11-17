from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_authenticated_user
from app.database import get_db
from app.models import AuditLog, BlocklistEntry, User
from app.phone import normalize_kenyan_mobile


router = APIRouter(prefix="/api/blocklist", tags=["blocklist"])


class BlockNumberRequest(BaseModel):
    phone_number: str = Field(min_length=8, max_length=24)
    reason: str | None = Field(default=None, max_length=255)


def can_manage(user: User) -> None:
    if user.role not in {"super_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


@router.get("")
def list_blocked(db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    can_manage(user)
    entries = db.scalars(select(BlocklistEntry).where(BlocklistEntry.removed_at.is_(None)).order_by(BlocklistEntry.created_at.desc())).all()
    return [{"id": entry.id, "phone_number": entry.phone_number, "reason": entry.reason, "created_at": entry.created_at} for entry in entries]


@router.post("", status_code=201)
def add_blocked(payload: BlockNumberRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    can_manage(user)
    number = normalize_kenyan_mobile(payload.phone_number)
    if not number:
        raise HTTPException(status_code=422, detail="Only Kenyan mobile numbers can be blocklisted")
    entry = db.scalar(select(BlocklistEntry).where(BlocklistEntry.phone_number == number))
    if entry:
        if entry.removed_at is None:
            raise HTTPException(status_code=409, detail="Number is already blocklisted")
        entry.reason = payload.reason
        entry.created_by = user.id
        entry.created_at = datetime.now(timezone.utc)
        entry.removed_at = None
    else:
        entry = BlocklistEntry(phone_number=number, reason=payload.reason, created_by=user.id, created_at=datetime.now(timezone.utc))
        db.add(entry)
    db.add(AuditLog(actor_id=user.id, action="number_blocked", entity="blocklist", entity_id=number, before=None, after={"reason": payload.reason}, ip_address=request.client.host if request.client else None, created_at=datetime.now(timezone.utc)))
    db.commit()
    return {"id": entry.id, "phone_number": entry.phone_number, "reason": entry.reason}


@router.delete("/{entry_id}", status_code=204)
def remove_blocked(entry_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    can_manage(user)
    entry = db.get(BlocklistEntry, entry_id)
    if not entry or entry.removed_at:
        raise HTTPException(status_code=404, detail="Blocklist entry not found")
    entry.removed_at = datetime.now(timezone.utc)
    db.add(AuditLog(actor_id=user.id, action="number_unblocked", entity="blocklist", entity_id=entry.phone_number, before={"reason": entry.reason}, after=None, ip_address=request.client.host if request.client else None, created_at=datetime.now(timezone.utc)))
    db.commit()