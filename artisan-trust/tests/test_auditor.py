import pytest
from sqlalchemy import text
from app.core.database import SessionLocal, init_db
from app.core.plumbline import append_entry
from app.core.auditor import audit_chain, audit_token


@pytest.fixture(scope="function")
def db():
    init_db()
    session = SessionLocal()
    session.execute(text("TRUNCATE TABLE merkle_ledger RESTART IDENTITY CASCADE;"))
    session.commit()
    yield session
    session.close()


def test_audit_chain_clean(db):
    append_entry(db, {"ref": "deal-1"})
    append_entry(db, {"ref": "deal-2"})
    assert audit_chain() is True


def test_audit_chain_tampered(db):
    b1 = append_entry(db, {"ref": "deal-1"})
    append_entry(db, {"ref": "deal-2"})

    # Intentionally corrupt payload in database
    db.execute(
        text("UPDATE merkle_ledger SET transaction_payload = '{\"ref\": \"falsified\"}' WHERE id = :id"),
        {"id": b1["id"]}
    )
    db.commit()

    assert audit_chain() is False


def test_audit_token_valid(db):
    import hashlib
    from app.core.config import settings

    wa_id = "254700112233"
    inquiry = "Inquiry for Nissan X-Trail"
    body_hash = hashlib.sha256(inquiry.encode("utf-8")).hexdigest()
    salt = f"{wa_id}{body_hash}{settings.LEDGER_SECRET}"
    token = hashlib.sha256(salt.encode("utf-8")).hexdigest()

    append_entry(db, {
        "event": "REFERRAL_ISSUED",
        "wa_id": wa_id,
        "signed_token": token,
        "status": "PENDING"
    })

    assert audit_token(token, wa_id, inquiry) is True
    assert audit_token("fake_token_hex", wa_id, inquiry) is False
