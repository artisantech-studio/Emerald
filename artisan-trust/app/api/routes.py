import hashlib
import os
import urllib.parse
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
import json
from app.api.middleware import verify_meta_hmac_signature

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.plumbline import append_entry, PlumblineIntegrityError, compute_hash

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


@router.get("/v1/ledger/blocks")
def get_ledger_blocks(db: Session = Depends(get_db)):
    """Fetches all blocks in the Merkle ledger for the frontend explorer."""
    rows = db.execute(
        text("""
            SELECT id, parent_hash, transaction_payload, timestamp, current_hash 
            FROM merkle_ledger 
            ORDER BY id DESC 
            LIMIT 100;
        """)
    ).fetchall()

    blocks = []
    for r in rows:
        blocks.append({
            "id": r.id,
            "parent_hash": r.parent_hash,
            "payload": r.transaction_payload,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "current_hash": r.current_hash
        })
    return blocks


@router.get("/v1/ledger/audit")
def audit_ledger_endpoint(db: Session = Depends(get_db)):
    """Executes full Merkle plumbline cryptographic audit and returns structured log."""
    rows = db.execute(
        text("""
            SELECT id, parent_hash, transaction_payload, timestamp, current_hash 
            FROM merkle_ledger 
            ORDER BY id ASC;
        """)
    ).fetchall()

    if not rows:
        return {"total_blocks": 0, "is_valid": True, "details": []}

    last_hash: Optional[str] = None
    details = []
    is_valid = True

    for row in rows:
        block_valid = True
        err = None

        if row.parent_hash != last_hash:
            block_valid = False
            is_valid = False
            err = f"Parent mismatch! Expected {last_hash}, found {row.parent_hash}"

        expected_hash = compute_hash(
            row.parent_hash,
            row.transaction_payload,
            row.timestamp.isoformat() if hasattr(row.timestamp, "isoformat") else str(row.timestamp)
        )

        if row.current_hash != expected_hash:
            block_valid = False
            is_valid = False
            err = f"Hash tamper detected! Expected {expected_hash}, recorded {row.current_hash}"

        details.append({
            "id": row.id,
            "parent_hash": row.parent_hash,
            "current_hash": row.current_hash,
            "valid": block_valid,
            "error": err
        })
        last_hash = row.current_hash

    return {
        "total_blocks": len(rows),
        "is_valid": is_valid,
        "details": details
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

# Serve Web App UI
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", response_class=FileResponse)
    def read_root():
        return FileResponse(os.path.join(static_dir, "index.html"))

app.include_router(router)

