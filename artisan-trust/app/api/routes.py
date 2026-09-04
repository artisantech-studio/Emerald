import hashlib
import urllib.parse
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import json
from app.api.middleware import verify_meta_hmac_signature

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.plumbline import append_entry, PlumblineIntegrityError

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def generate_attribution_token(wa_id: str, body_hash: str) -> str:
    """
    Computes a cryptographic signature: SHA-256(wa_id + body_hash + LEDGER_SECRET).
    Guarantees that attribution metadata cannot be spoofed or detached.
    """
    raw_salt = f"{wa_id}{body_hash}{settings.LEDGER_SECRET}"
    return hashlib.sha256(raw_salt.encode("utf-8")).hexdigest()


# ---------------------------------------------------------
# Schemas
# ---------------------------------------------------------

class ReferralSignRequest(BaseModel):
    broker_id: str = Field(..., description="Unique UUID or identifier for the broker")
    merchant_phone: str = Field(..., description="Merchant WhatsApp phone number (E.164, digits only)")
    wa_id: str = Field(..., description="Client/Buyer WhatsApp ID or phone number")
    inquiry_text: str = Field(..., description="Raw text of the vehicle/asset inquiry")


class ReferralVerifyRequest(BaseModel):
    token: str = Field(..., description="The signed token presented at settlement")
    wa_id: str = Field(..., description="Client/Buyer WhatsApp ID")
    inquiry_text: str = Field(..., description="Original raw inquiry text")


# ---------------------------------------------------------
# Endpoints
# ---------------------------------------------------------

@router.post("/v1/referral/sign", status_code=status.HTTP_201_CREATED)
def sign_referral(packet: ReferralSignRequest, db: Session = Depends(get_db)):
    """
    Generates an attribution token, appends a PENDING referral to the Merkle log,
    and returns the merchant WhatsApp click-to-chat redirect link.
    """
    body_hash = hashlib.sha256(packet.inquiry_text.encode("utf-8")).hexdigest()
    signed_token = generate_attribution_token(packet.wa_id, body_hash)

    # Encode message with embedded verification token for WhatsApp redirect
    encoded_message = urllib.parse.quote(
        f"{packet.inquiry_text}\n[RefToken:{signed_token}]"
    )
    redirect_url = f"https://wa.me/{packet.merchant_phone}?text={encoded_message}"

    payload: Dict[str, Any] = {
        "event": "REFERRAL_ISSUED",
        "broker_id": packet.broker_id,
        "merchant_phone": packet.merchant_phone,
        "wa_id": packet.wa_id,
        "body_hash": body_hash,
        "signed_token": signed_token,
        "status": "PENDING"
    }

    try:
        block = append_entry(db, payload)
    except PlumblineIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record referral on ledger: {str(exc)}"
        )

    return {
        "status": "ISSUED",
        "signed_token": signed_token,
        "redirect_url": redirect_url,
        "merkle_block": block
    }


@router.post("/v1/referral/verify")
def verify_referral(packet: ReferralVerifyRequest, db: Session = Depends(get_db)):
    """
    Verifies token validity against cryptographic metadata.
    Re-hashes inputs and commits an immutably settled commission state.
    """
    body_hash = hashlib.sha256(packet.inquiry_text.encode("utf-8")).hexdigest()
    expected_token = generate_attribution_token(packet.wa_id, body_hash)

    if packet.token != expected_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Attribution token invalid: cryptographic verification failed."
        )

    payload: Dict[str, Any] = {
        "event": "REFERRAL_VERIFIED",
        "wa_id": packet.wa_id,
        "body_hash": body_hash,
        "signed_token": packet.token,
        "status": "SETTLED"
    }

    try:
        block = append_entry(db, payload)
    except PlumblineIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to commit verification to ledger: {str(exc)}"
        )

    return {
        "status": "SETTLED",
        "signed_token": packet.token,
        "merkle_block": block
    }


@router.get("/webhook")
def whatsapp_webhook_handshake(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
):
    """Handles standard WhatsApp Cloud API webhook registration handshake."""
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Handshake verification failed")


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def whatsapp_webhook_inbound(
    raw_body: bytes = Depends(verify_meta_hmac_signature),
    db: Session = Depends(get_db)
):
    """
    Parses inbound messages from WhatsApp after HMAC validation,
    hashes the body, and commits a record to the append-only Merkle ledger.
    """
    try:
        data = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

    inbound_hash = hashlib.sha256(raw_body).hexdigest()

    payload: Dict[str, Any] = {
        "event": "INBOUND_WHATSAPP_WEBHOOK",
        "inbound_hash": inbound_hash,
        "raw_event": data
    }

    try:
        block = append_entry(db, payload)
    except PlumblineIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Plumbline logging failed: {str(exc)}"
        )

    return {"status": "RECORDED", "merkle_block_id": block["id"]}

from fastapi import FastAPI

app = FastAPI(
    title="Artisan Trust-Link Gateway",
    version="1.0.0",
    description="Lightweight Cryptographic Referral Notary for African B2B Trade"
)

app.include_router(router)
