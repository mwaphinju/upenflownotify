from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import get_authenticated_user
from app.database import get_db
from app.models import AuditLog, InboundMessage, MappingRule, MappingRuleVersion, User
from app.rule_matching import match_rule, render_template, sms_segments, validate_rule, values_for

router = APIRouter(tags=["mapping rules"])


class RuleFields(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    priority: int = Field(ge=0)
    match_type: Literal["contains", "starts_with", "exact", "regex"]
    match_value: str = Field(min_length=1, max_length=1000)
    case_sensitive: bool = False
    sender_id: str = Field(min_length=1, max_length=11, pattern=r"^[A-Za-z0-9 ]+$")
    outbound_template: str = Field(min_length=1, max_length=1600)
    is_enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    priority: int | None = Field(default=None, ge=0)
    match_type: Literal["contains", "starts_with", "exact", "regex"] | None = None
    match_value: str | None = Field(default=None, min_length=1, max_length=1000)
    case_sensitive: bool | None = None
    sender_id: str | None = Field(default=None, min_length=1, max_length=11, pattern=r"^[A-Za-z0-9 ]+$")
    outbound_template: str | None = Field(default=None, min_length=1, max_length=1600)
    is_enabled: bool | None = None


class RuleTestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    recipient: str = "254700000000"
    order_ref: str | None = None


class ReorderRequest(BaseModel):
    rule_ids: list[int] = Field(min_length=1)


def rule_snapshot(rule: MappingRule) -> dict:
    return {
        "name": rule.name,
        "priority": rule.priority,
        "match_type": rule.match_type,
        "match_value": rule.match_value,
        "case_sensitive": rule.case_sensitive,
        "sender_id": rule.sender_id,
        "outbound_template": rule.outbound_template,
        "is_enabled": rule.is_enabled,
    }


def public_rule(rule: MappingRule) -> dict:
    return {"id": rule.id, **rule_snapshot(rule), "version": rule.version}


def add_audit(db: Session, actor: User, action: str, entity_id: str, before: dict | None, after: dict | None, request: Request):
    db.add(
        AuditLog(
            actor_id=actor.id,
            action=action,
            entity="mapping_rule",
            entity_id=entity_id,
            before=before,
            after=after,
            ip_address=request.client.host if request.client else None,
            created_at=datetime.now(timezone.utc),
        )
    )


def require_rule_editor(user: User = Depends(get_authenticated_user)) -> User:
    if user.role not in {"super_admin", "operator"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user


@router.get("/api/rules")
def list_rules(db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    rules = db.scalars(
        select(MappingRule).where(MappingRule.deleted_at.is_(None)).order_by(MappingRule.priority, MappingRule.id)
    ).all()
    return [public_rule(rule) for rule in rules]


@router.post("/api/rules", status_code=status.HTTP_201_CREATED)
def create_rule(fields: RuleFields, request: Request, db: Session = Depends(get_db), user: User = Depends(require_rule_editor)):
    data = fields.model_dump()
    validate_rule(data)
    now = datetime.now(timezone.utc)
    rule = MappingRule(**data, version=1, created_by=user.id, updated_by=user.id)
    db.add(rule)
    db.flush()
    db.add(MappingRuleVersion(rule_id=rule.id, version=1, snapshot=data, created_by=user.id, created_at=now))
    add_audit(db, user, "created", str(rule.id), None, data, request)
    db.commit()
    return public_rule(rule)


@router.patch("/api/rules/reorder")
def reorder_rules(payload: ReorderRequest, request: Request, db: Session = Depends(get_db), user: User = Depends(require_rule_editor)):
    rules = db.scalars(
        select(MappingRule).where(MappingRule.id.in_(payload.rule_ids), MappingRule.deleted_at.is_(None))
    ).all()
    if len(rules) != len(payload.rule_ids) or len(set(payload.rule_ids)) != len(payload.rule_ids):
        raise HTTPException(status_code=422, detail="Provide each active rule ID exactly once")
    by_id = {rule.id: rule for rule in rules}
    now = datetime.now(timezone.utc)
    for priority, rule_id in enumerate(payload.rule_ids, start=1):
        rule = by_id[rule_id]
        before = rule_snapshot(rule)
        rule.priority = priority
        rule.version += 1
        rule.updated_by = user.id
        after = rule_snapshot(rule)
        db.add(MappingRuleVersion(rule_id=rule.id, version=rule.version, snapshot=after, created_by=user.id, created_at=now))
        add_audit(db, user, "reordered", str(rule.id), before, after, request)
    db.commit()
    return [public_rule(by_id[rule_id]) for rule_id in payload.rule_ids]


@router.post("/api/rules/test")
def test_rule(payload: RuleTestRequest, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    rules = db.scalars(
        select(MappingRule).where(MappingRule.deleted_at.is_(None)).order_by(MappingRule.priority, MappingRule.id)
    ).all()
    for rule in rules:
        groups = match_rule(rule, payload.text)
        if groups is None:
            continue
        rendered = render_template(
            rule.outbound_template,
            values_for(payload.text, payload.recipient, payload.order_ref, groups),
        )
        segments, encoding, units = sms_segments(rendered)
        return {
            "rule": public_rule(rule),
            "status": "Queued" if rule.is_enabled else "Suppressed",
            "rendered_text": rendered,
            "character_count": len(rendered),
            "encoding": encoding,
            "encoding_units": units,
            "segments": segments,
            "warnings": ["Message exceeds 3 SMS segments"] if segments > 3 else [],
        }
    return {"rule": None, "status": "Unmapped", "rendered_text": None, "segments": 0, "warnings": []}


@router.patch("/api/rules/{rule_id}")
def update_rule(rule_id: int, changes: RuleUpdate, request: Request, db: Session = Depends(get_db), user: User = Depends(require_rule_editor)):
    rule = db.get(MappingRule, rule_id)
    if not rule or rule.deleted_at:
        raise HTTPException(status_code=404, detail="Rule not found")
    before = rule_snapshot(rule)
    updated = before | changes.model_dump(exclude_unset=True)
    validate_rule(updated)
    now = datetime.now(timezone.utc)
    for key, value in updated.items():
        setattr(rule, key, value)
    if rule.is_enabled is False:
        db.execute(
            update(InboundMessage)
            .where(InboundMessage.rule_id == rule.id, InboundMessage.status == "Queued")
            .values(status="Suppressed", status_reason="Mapping rule disabled")
        )
    rule.version += 1
    rule.updated_by = user.id
    db.add(MappingRuleVersion(rule_id=rule.id, version=rule.version, snapshot=updated, created_by=user.id, created_at=now))
    add_audit(db, user, "updated", str(rule.id), before, updated, request)
    db.commit()
    return public_rule(rule)


@router.delete("/api/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_rule_editor)):
    rule = db.get(MappingRule, rule_id)
    if not rule or rule.deleted_at:
        raise HTTPException(status_code=404, detail="Rule not found")
    before = rule_snapshot(rule)
    rule.deleted_at = datetime.now(timezone.utc)
    rule.version += 1
    rule.updated_by = user.id
    add_audit(db, user, "deleted", str(rule.id), before, None, request)
    db.commit()


@router.get("/api/rules/{rule_id}/versions")
def list_rule_versions(rule_id: int, db: Session = Depends(get_db), user: User = Depends(get_authenticated_user)):
    rule = db.get(MappingRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    versions = db.scalars(
        select(MappingRuleVersion).where(MappingRuleVersion.rule_id == rule_id).order_by(MappingRuleVersion.version.desc())
    ).all()
    return [
        {"version": version.version, "snapshot": version.snapshot, "created_by": version.created_by, "created_at": version.created_at}
        for version in versions
    ]


@router.post("/api/rules/{rule_id}/versions/{version}/restore")
def restore_rule_version(rule_id: int, version: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_rule_editor)):
    rule = db.get(MappingRule, rule_id)
    if not rule or rule.deleted_at:
        raise HTTPException(status_code=404, detail="Rule not found")
    target = db.scalar(
        select(MappingRuleVersion).where(MappingRuleVersion.rule_id == rule_id, MappingRuleVersion.version == version)
    )
    if not target:
        raise HTTPException(status_code=404, detail="Rule version not found")
    before = rule_snapshot(rule)
    snapshot = target.snapshot
    validate_rule(snapshot)
    now = datetime.now(timezone.utc)
    for key, value in snapshot.items():
        setattr(rule, key, value)
    rule.version += 1
    rule.updated_by = user.id
    db.add(MappingRuleVersion(rule_id=rule.id, version=rule.version, snapshot=rule_snapshot(rule), created_by=user.id, created_at=now))
    add_audit(db, user, "restored", str(rule.id), before, rule_snapshot(rule), request)
    db.commit()
    return public_rule(rule)
