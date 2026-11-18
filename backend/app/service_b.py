import hmac
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.models import AuditLog, BlocklistEntry, InboundMessage
from app.phone import normalize_kenyan_mobile


router = APIRouter(prefix="/api/dlr", tags=["delivery reports"])
reply_router = APIRouter(prefix="/api/inbound", tags=["delivery reports"])
logger = logging.getLogger("upenflow.dlr")

# Onfon's push DLR uses "000"/"0" for a successful delivery and any other value for a failure.
# There's no published table of failure codes, so anything else is simply "Failed" with the
# gateway's own shortMessage recorded for context.
DLR_SUCCESS_ERROR_CODES = {"0", "000"}


class ServiceBReply(BaseModel):
    sender: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=1000)


class ServiceBError(Exception):
    def __init__(self, message: str, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


class ServiceBAdapter:
    """Onfon Media SendBulkSMS adapter. One call = one message (immediate send, never scheduled)."""

    def __init__(self, base_url: str, api_key: str, client_id: str | None = None, access_key: str | None = None, timeout: float = 10.0, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client_id = client_id
        self.access_key = access_key
        self.timeout = timeout
        self.client = client

    def send(self, sender_id: str, to: str, text: str, message_key: str, is_unicode: bool = False) -> str | None:
        client = self.client or httpx
        try:
            response = client.post(
                self.base_url,
                json={
                    "SenderId": sender_id,
                    "IsUnicode": is_unicode,
                    "MessageParameters": [{"Number": to, "Text": text}],
                    "ApiKey": self.api_key,
                    "ClientId": self.client_id,
                },
                headers={"Content-Type": "application/json", "AccessKey": self.access_key or ""},
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
        except ValueError as error:
            raise ServiceBError("Gateway returned a non-JSON response", retryable=True) from error
        error_code = result.get("ErrorCode")
        if error_code not in (0, None):
            # Onfon's error-code table isn't wired up yet, so every rejected send is treated as
            # permanent (not retried) rather than guessing which codes are transient.
            raise ServiceBError(result.get("ErrorDescription") or f"Gateway rejected the message (ErrorCode {error_code})", retryable=False)
        data = result.get("Data") or []
        return data[0].get("MessageId") if data else None

    def get_balance(self) -> Decimal:
        """Onfon's SMS credit balance, e.g. "KSh7578560.8000" -> Decimal("7578560.8000")."""
        client = self.client or httpx
        balance_url = self.base_url.rsplit("/", 1)[0] + "/Balance"
        try:
            response = client.get(
                balance_url,
                params={"ApiKey": self.api_key, "ClientId": self.client_id},
                headers={"Content-Type": "application/json", "AccessKey": self.access_key or ""},
                timeout=self.timeout,
            )
        except httpx.TimeoutException as error:
            raise ServiceBError("Balance check timed out", retryable=True) from error
        except httpx.NetworkError as error:
            raise ServiceBError("Balance check network error", retryable=True) from error
        if response.status_code >= 500:
            raise ServiceBError(f"Balance check returned HTTP {response.status_code}", retryable=True)
        if response.status_code >= 400:
            raise ServiceBError(f"Balance check returned HTTP {response.status_code}", retryable=False)
        try:
            result = response.json()
        except ValueError as error:
            raise ServiceBError("Balance check returned a non-JSON response", retryable=True) from error
        error_code = result.get("ErrorCode")
        if error_code not in (0, None):
            raise ServiceBError(result.get("ErrorDescription") or f"Balance check failed (ErrorCode {error_code})", retryable=False)
        data = result.get("Data") or []
        sms_credits = next((row.get("Credits") for row in data if row.get("PluginType") == "SMS"), None)
        if sms_credits is None and data:
            sms_credits = data[0].get("Credits")
        numeric = re.sub(r"[^0-9.]", "", str(sms_credits or "0")) or "0"
        try:
            return Decimal(numeric)
        except InvalidOperation as error:
            raise ServiceBError(f"Balance check returned an unparseable value: {sms_credits!r}", retryable=False) from error


def record_delivery_report(
    db: Session,
    message_id: str,
    status: str | None,
    error_code: str | None,
    short_message: str | None,
    mobile: str | None,
) -> dict:
    message = db.scalar(select(InboundMessage).where(InboundMessage.provider_message_id == message_id))
    if not message:
        # Onfon does not retry a push DLR if the remote server is unavailable, and there is no
        # documented failure response for an unmatched ID — always ack 200 so a stale/unknown ID
        # (e.g. purged by retention) doesn't make Onfon think this endpoint is unhealthy.
        logger.warning("dlr_unmatched_message_id", extra={"fields": {"message_id": message_id, "status": status, "error_code": error_code}})
        return {"accepted": True, "matched": False}

    delivered = (error_code in DLR_SUCCESS_ERROR_CODES) if error_code is not None else bool(status and "deliver" in status.lower())
    message.status = "Delivered" if delivered else "Failed"
    message.error = None if delivered else (short_message or (f"Delivery failed (errorCode {error_code})" if error_code else "Delivery failed"))
    if delivered:
        message.delivered_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("dlr_received", extra={"fields": {"message_id": message_id, "status": status, "error_code": error_code, "mobile": mobile, "matched": True}})
    return {"accepted": True, "matched": True}


def check_dlr_token(settings: Settings, provided: str | None) -> None:
    if settings.service_b_dlr_token and not hmac.compare_digest(provided or "", settings.service_b_dlr_token):
        raise HTTPException(status_code=401, detail="Invalid delivery report token")


@router.get("/service-b", status_code=200)
def delivery_report(
    request: Request,
    db: Session = Depends(get_db),
    messageId: str = Query(..., max_length=255),
    status: str | None = Query(default=None, max_length=64),
    errorCode: str | None = Query(default=None, max_length=16),
    shortMessage: str | None = Query(default=None, max_length=500),
    doneDate: str | None = Query(default=None, max_length=32),
    submitDate: str | None = Query(default=None, max_length=32),
    mobile: str | None = Query(default=None, max_length=32),
):
    """Onfon's push DLR callback: a plain GET with no documented authentication (see
    docs/service-b-onfon-integration.md). If UPENFLOW_SERVICE_B_DLR_TOKEN is set, register the
    /service-b/{token} path below with Onfon instead of this bare path for a lightweight check —
    a query-string secret isn't used here since Onfon's own example builds the callback URL as
    `base + "?" + their_params`, which would corrupt a `?token=...` already on the URL."""
    check_dlr_token(request.app.state.settings, None)
    return record_delivery_report(db, messageId, status, errorCode, shortMessage, mobile)


@router.get("/service-b/{token}", status_code=200)
def delivery_report_with_token(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
    messageId: str = Query(..., max_length=255),
    status: str | None = Query(default=None, max_length=64),
    errorCode: str | None = Query(default=None, max_length=16),
    shortMessage: str | None = Query(default=None, max_length=500),
    doneDate: str | None = Query(default=None, max_length=32),
    submitDate: str | None = Query(default=None, max_length=32),
    mobile: str | None = Query(default=None, max_length=32),
):
    check_dlr_token(request.app.state.settings, token)
    return record_delivery_report(db, messageId, status, errorCode, shortMessage, mobile)


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