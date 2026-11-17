import hashlib
import hmac
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.models import AuditLog, BlocklistEntry, InboundMessage
from app.phone import normalize_kenyan_mobile


router = APIRouter(prefix="/api/dlr", tags=["delivery reports"])
reply_router = APIRouter(prefix="/api/inbound", tags=["delivery reports"])


class DeliveryReport(BaseModel):
    provider_message_id: str = Field(min_length=1, max_length=255)
    status: str = Field(pattern=r"^(delivered|failed|Delivered|Failed)$")
    error: str | None = Field(default=None, max_length=1000)


class ServiceBReply(BaseModel):
    sender: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=1000)


def verify_service_b_request(settings: Settings, raw_body: bytes, service_key: str | None, timestamp: str | None, signature: str | None) -> None:
    if not settings.service_b_dlr_api_key or not settings.service_b_dlr_hmac_secret:
        raise HTTPException(status_code=503, detail="Delivery report authentication is not configured")
    if not service_key or not hmac.compare_digest(service_key, settings.service_b_dlr_api_key):
        raise HTTPException(status_code=401, detail="Invalid delivery report credentials")
    try:
        timestamp_value = int(timestamp or "")
    except ValueError as error:
        raise HTTPException(status_code=401, detail="Invalid delivery report timestamp") from error
    if abs(time.time() - timestamp_value) > 300:
        raise HTTPException(status_code=401, detail="Delivery report timestamp expired")
    expected = hmac.new(
        settings.service_b_dlr_hmac_secret.encode(),
        (timestamp or "").encode() + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    supplied = (signature or "").removeprefix("sha256=")
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid delivery report signature")


class ServiceBError(Exception):
    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


class ServiceBAdapter:
    def __init__(self, base_url: str, api_key: str, username: str | None = None, timeout: float = 10.0, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.username = username
        self.timeout = timeout
        self.client = client

    def send(self, sender_id: str, to: str, text: str, message_key: str) -> str | None:
        client = self.client or httpx
        try:
            response = client.post(
                self.base_url,
                json={"sender_id": sender_id, "to": to, "text": text, "username": self.username},
                headers={"Authorization": f"Bearer {self.api_key}", "Idempotency-Key": message_key},
                timeout=self.timeout,
            )
        except httpx.TimeoutException as error:
            raise ServiceBError("Gateway request timed out", retryable=True) from error
        except httpx.NetworkError as error:
            raise ServiceBError("Gateway network error", retryable=True) from error
        if response.status_code >= 500:
            raise ServiceBError(f"Gateway returned HTTP {response.status_code}", retryable=True)
        if response.status_code >= 400:
            raise ServiceBError(f"Gateway returned HTTP {response.status_code}", retryable=False)
        try:
            result = response.json()
        except ValueError:
            return None
        return result.get("provider_message_id") or result.get("message_id") or result.get("id")


@router.post("/service-b", status_code=202)
async def delivery_report(
    request: Request,
    db: Session = Depends(get_db),
    service_key: str | None = Header(default=None, alias="X-Service-B-Key"),
    timestamp: str | None = Header(default=None, alias="X-Service-B-Timestamp"),
    signature: str | None = Header(default=None, alias="X-Service-B-Signature"),
):
    settings: Settings = request.app.state.settings
    raw_body = await request.body()
    verify_service_b_request(settings, raw_body, service_key, timestamp, signature)
    payload = DeliveryReport.model_validate_json(raw_body)
    message = db.scalar(select(InboundMessage).where(InboundMessage.provider_message_id == payload.provider_message_id))
    if not message:
        raise HTTPException(status_code=404, detail="Provider message not found")
    message.status = "Delivered" if payload.status.lower() == "delivered" else "Failed"
    message.error = payload.error
    if message.status == "Delivered":
        message.delivered_at = datetime.now(timezone.utc)
    db.commit()
    return {"accepted": True}


@reply_router.post("/service-b-reply", status_code=202)
async def service_b_reply(
    request: Request,
    db: Session = Depends(get_db),
    service_key: str | None = Header(default=None, alias="X-Service-B-Key"),
):
    settings: Settings = request.app.state.settings
    if not settings.service_b_reply_api_key:
        raise HTTPException(status_code=503, detail="Reply ingestion is not configured")
    if not service_key or not hmac.compare_digest(service_key, settings.service_b_reply_api_key):
        raise HTTPException(status_code=401, detail="Invalid reply credentials")
    payload = ServiceBReply.model_validate_json(await request.body())
    number = normalize_kenyan_mobile(payload.sender)
    if not number or payload.text.strip().upper() != "STOP":
        return {"accepted": True, "blocked": False}
    now = datetime.now(timezone.utc)
    entry = db.scalar(select(BlocklistEntry).where(BlocklistEntry.phone_number == number))
    if entry:
        if entry.removed_at is not None:
            entry.removed_at = None
            entry.reason = "Customer sent STOP"
            entry.created_at = now
    else:
        db.add(BlocklistEntry(phone_number=number, reason="Customer sent STOP", created_by=None, created_at=now))
    db.add(
        AuditLog(
            actor_id=None,
            action="number_blocked",
            entity="blocklist",
            entity_id=number,
            before=None,
            after={"reason": "Customer sent STOP"},
            created_at=now,
        )
    )
    db.commit()
    return {"accepted": True, "blocked": True}