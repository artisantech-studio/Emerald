import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session


class PlumblineIntegrityError(Exception):
    """Raised when ledger verification or insertion violates the chain."""
    pass


def canonical_serialize(payload: Dict[str, Any]) -> str:
    """Produces deterministic, whitespace-stripped JSON string."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_hash(parent_hash: Optional[str], payload: Dict[str, Any], timestamp_iso: str) -> str:
    """
    Computes SHA-256 over: parent_hash + timestamp_iso + canonical(payload).
    Genesis blocks pass an empty string for parent_hash.
    """
    anchor = parent_hash if parent_hash is not None else ""
    serialized = canonical_serialize(payload)
    raw = f"{anchor}{timestamp_iso}{serialized}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def append_entry(db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Atomically appends a block to the Merkle chain with row-level locking
    to guarantee strict linear ordering under concurrent execution.
    """
    # Lock table in EXCLUSIVE mode to guarantee strict linear ordering under concurrent execution
    db.execute(text("LOCK TABLE merkle_ledger IN EXCLUSIVE MODE;"))
    tail_query = text("""
        SELECT current_hash 
        FROM merkle_ledger 
        ORDER BY id DESC 
        LIMIT 1;
    """)
    last_block = db.execute(tail_query).fetchone()
    parent_hash = last_block[0] if last_block else None

    # 2. Derive canonical UTC timestamp
    timestamp = datetime.now(timezone.utc).isoformat()

    # 3. Compute immutable block hash
    current_hash = compute_hash(parent_hash, payload, timestamp)

    # 4. Insert stone into the ledger
    insert_query = text("""
        INSERT INTO merkle_ledger (parent_hash, transaction_payload, timestamp, current_hash)
        VALUES (:parent_hash, :payload, :timestamp, :current_hash)
        RETURNING id, parent_hash, transaction_payload, timestamp, current_hash;
    """)
    
    try:
        result = db.execute(
            insert_query,
            {
                "parent_hash": parent_hash,
                "payload": json.dumps(payload),
                "timestamp": timestamp,
                "current_hash": current_hash,
            },
        ).fetchone()
        db.commit()
    except Exception as exc:
        db.rollback()
        raise PlumblineIntegrityError(f"Chain rejection at plumbline: {str(exc)}") from exc

    return {
        "id": result.id,
        "parent_hash": result.parent_hash,
        "payload": result.transaction_payload,
        "timestamp": str(result.timestamp),
        "current_hash": result.current_hash,
    }


def verify_chain_integrity(db: Session) -> bool:
    """
    Traverses the entire ledger from Genesis to head.
    Returns True if every parent reference and SHA-256 computation is sound.
    """
    query = text("""
        SELECT id, parent_hash, transaction_payload, timestamp, current_hash 
        FROM merkle_ledger 
        ORDER BY id ASC;
    """)
    rows = db.execute(query).fetchall()

    last_hash = None
    for row in rows:
        # Check foreign key chain continuity
        if row.parent_hash != last_hash:
            return False

        # Re-compute hash from row data
        expected = compute_hash(row.parent_hash, row.transaction_payload, row.timestamp.isoformat())
        if row.current_hash != expected:
            return False

        last_hash = row.current_hash

    return True
