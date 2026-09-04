import pytest
from sqlalchemy import text
from app.core.database import SessionLocal, init_db
from app.core.plumbline import (
    append_entry,
    verify_chain_integrity,
    canonical_serialize,
)


@pytest.fixture(scope="function")
def db_session():
    """Initializes the Plumbline schema and clears the ledger for a clean test run."""
    init_db()
    session = SessionLocal()
    # Reset table before test
    session.execute(text("TRUNCATE TABLE merkle_ledger RESTART IDENTITY CASCADE;"))
    session.commit()
    yield session
    session.close()


def test_genesis_block_creation(db_session):
    payload = {"broker_id": "agent-001", "event": "referral_created", "amount": 25000}
    block = append_entry(db_session, payload)

    assert block["id"] == 1
    assert block["parent_hash"] is None
    assert isinstance(block["current_hash"], str)
    assert len(block["current_hash"]) == 64
    assert block["payload"] == payload
    assert verify_chain_integrity(db_session) is True


def test_linear_chain_succession(db_session):
    payload_1 = {"broker_id": "agent-001", "step": "inquiry"}
    block_1 = append_entry(db_session, payload_1)

    payload_2 = {"broker_id": "agent-001", "step": "inspection_scheduled"}
    block_2 = append_entry(db_session, payload_2)

    payload_3 = {"broker_id": "agent-001", "step": "deal_closed"}
    block_3 = append_entry(db_session, payload_3)

    assert block_2["parent_hash"] == block_1["current_hash"]
    assert block_3["parent_hash"] == block_2["current_hash"]
    assert verify_chain_integrity(db_session) is True


def test_db_foreign_key_plumbline_rejection(db_session):
    """
    Directly attempts to insert an out-of-order parent_hash.
    PostgreSQL foreign key constraint must reject the unhewn stone.
    """
    fake_parent_hash = "0000000000000000000000000000000000000000000000000000000000000000"
    raw_insert = text("""
        INSERT INTO merkle_ledger (parent_hash, transaction_payload, current_hash)
        VALUES (:parent_hash, :payload, :current_hash);
    """)

    with pytest.raises(Exception):  # Catches DB IntegrityError / ForeignKeyViolation
        db_session.execute(
            raw_insert,
            {
                "parent_hash": fake_parent_hash,
                "payload": '{"violation": true}',
                "current_hash": "1111111111111111111111111111111111111111111111111111111111111111",
            },
        )
        db_session.commit()
    db_session.rollback()


def test_tamper_detection(db_session):
    """Verifies that tampering with historical rows invalidates the chain."""
    block_1 = append_entry(db_session, {"trade": "yard_unit_1"})
    block_2 = append_entry(db_session, {"trade": "yard_unit_2"})

    # Tamper directly with the payload of block 1
    db_session.execute(
        text("UPDATE merkle_ledger SET transaction_payload = :payload WHERE id = :id"),
        {"payload": '{"trade": "yard_unit_1_falsified"}', "id": block_1["id"]},
    )
    db_session.commit()

    # The plumbline verification must detect the discrepancy
    assert verify_chain_integrity(db_session) is False
