import pytest
import hmac
import hashlib
import json
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.routes import app
from app.core.config import settings
from app.core.database import SessionLocal, init_db


@pytest.fixture(scope="function")
def client():
    """Initializes the database schema and clears tables for integration tests."""
    init_db()
    session = SessionLocal()
    session.execute(text("TRUNCATE TABLE merkle_ledger RESTART IDENTITY CASCADE;"))
    session.commit()
    session.close()

    with TestClient(app) as test_client:
        yield test_client


def test_whatsapp_webhook_handshake(client):
    # Valid handshake
    params = {
        "hub.mode": "subscribe",
        "hub.challenge": "1158201444",
        "hub.verify_token": settings.WHATSAPP_VERIFY_TOKEN,
    }
    response = client.get("/webhook", params=params)
    assert response.status_code == 200
    assert response.text == "1158201444"

    # Invalid token rejection
    bad_params = {
        "hub.mode": "subscribe",
        "hub.challenge": "1158201444",
        "hub.verify_token": "wrong_secret_token",
    }
    bad_response = client.get("/webhook", params=bad_params)
    assert bad_response.status_code == 403


def test_sign_referral_flow(client):
    packet = {
        "broker_id": "broker-uuid-001",
        "merchant_phone": "254700000000",
        "wa_id": "254711111111",
        "inquiry_text": "Inquiry regarding Toyota Prado 2021 KDA",
    }

    response = client.post("/v1/referral/sign", json=packet)
    assert response.status_code == 201

    data = response.json()
    assert data["status"] == "ISSUED"
    assert "signed_token" in data
    assert len(data["signed_token"]) == 64
    assert "https://wa.me/254700000000?text=" in data["redirect_url"]
    assert data["signed_token"] in data["redirect_url"]
    assert data["merkle_block"]["parent_hash"] is None


def test_referral_verification_and_settlement(client):
    inquiry = "Inquiry regarding Isuzu FRR Truck"
    wa_id = "254722222222"

    # 1. Sign initial referral
    sign_packet = {
        "broker_id": "broker-uuid-002",
        "merchant_phone": "254700000000",
        "wa_id": wa_id,
        "inquiry_text": inquiry,
    }
    sign_resp = client.post("/v1/referral/sign", json=sign_packet)
    assert sign_resp.status_code == 201
    signed_token = sign_resp.json()["signed_token"]

    # 2. Attempt verify with forged inquiry text -> Must fail (400)
    fraud_verify = {
        "token": signed_token,
        "wa_id": wa_id,
        "inquiry_text": "Altered vehicle inquiry details",
    }
    fail_resp = client.post("/v1/referral/verify", json=fraud_verify)
    assert fail_resp.status_code == 400

    # 3. Legitimate verify -> Must succeed and commit to ledger
    valid_verify = {
        "token": signed_token,
        "wa_id": wa_id,
        "inquiry_text": inquiry,
    }
    success_resp = client.post("/v1/referral/verify", json=valid_verify)
    assert success_resp.status_code == 200
    verify_data = success_resp.json()
    assert verify_data["status"] == "SETTLED"
    assert verify_data["merkle_block"]["parent_hash"] is not None


def test_inbound_webhook_hmac_validation(client):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "ACCOUNT_ID", "changes": []}]
    }
    raw_body = json.dumps(payload).encode("utf-8")

    # 1. Unsigned request -> 403
    unsigned_resp = client.post(
        "/webhook",
        content=raw_body,
        headers={"Content-Type": "application/json"}
    )
    assert unsigned_resp.status_code == 401

    # 2. Tampered signature -> 401
    bad_sig_resp = client.post(
        "/webhook",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=invalidhashvalue00000000000000000000000000000000000000000000000000"
        }
    )
    assert bad_sig_resp.status_code == 401

    # 3. Legitimate signed payload -> 200 RECORDED
    signature = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    valid_resp = client.post(
        "/webhook",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={signature}"
        }
    )
    assert valid_resp.status_code == 200
    assert valid_resp.json()["status"] == "RECORDED"
