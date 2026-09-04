import argparse
import hashlib
import json
import sys
from typing import Optional
from sqlalchemy import text
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.plumbline import compute_hash


def audit_chain() -> bool:
    """
    Traverses the entire ledger from Genesis, recalculating SHA-256 hashes
    and validating linear continuity across parent references.
    """
    session = SessionLocal()
    try:
        rows = session.execute(
            text("""
                SELECT id, parent_hash, transaction_payload, timestamp, current_hash 
                FROM merkle_ledger 
                ORDER BY id ASC;
            """)
        ).fetchall()

        if not rows:
            print("[INFO] Ledger is empty. No entries to verify.")
            return True

        print(f"\n====================== AUDITING MERKLE PLUMBLINE ({len(rows)} BLOCKS) ======================")
        last_hash: Optional[str] = None

        for idx, row in enumerate(rows, start=1):
            # Check 1: Parent Hash Chain Continuity
            if row.parent_hash != last_hash:
                print(f"[FAIL] Block #{row.id} Parent Discontinuity!")
                print(f"       Expected: {last_hash}")
                print(f"       Found:    {row.parent_hash}")
                return False

            # Check 2: Payload Hash Recomputation
            expected_hash = compute_hash(
                row.parent_hash,
                row.transaction_payload,
                row.timestamp.isoformat()
            )

            if row.current_hash != expected_hash:
                print(f"[FAIL] Block #{row.id} Hash Tampering Detected!")
                print(f"       Calculated: {expected_hash}")
                print(f"       Recorded:   {row.current_hash}")
                return False

            print(f"[OK] Block #{row.id} | Parent: {(row.parent_hash[:8] + '...') if row.parent_hash else 'GENESIS':<12} | Hash: {row.current_hash[:16]}...")
            last_hash = row.current_hash

        print("\n[SUCCESS] The Plumbline is true. All blocks verified cryptographically.")
        return True

    finally:
        session.close()


def audit_token(token: str, wa_id: str, inquiry_text: str) -> bool:
    """
    Validates attribution authenticity and locates token persistence in the ledger.
    """
    body_hash = hashlib.sha256(inquiry_text.encode("utf-8")).hexdigest()
    raw_salt = f"{wa_id}{body_hash}{settings.LEDGER_SECRET}"
    recomputed_token = hashlib.sha256(raw_salt.encode("utf-8")).hexdigest()

    print(f"\n====================== AUDITING ATTRIBUTION TOKEN ======================")
    print(f"Target Token:    {token}")
    print(f"Computed Token:  {recomputed_token}")

    if token != recomputed_token:
        print("[FAIL] Cryptographic signature invalid: Metadata does not produce this token.")
        return False

    print("[OK] Cryptographic signature matches metadata.")

    # Search the ledger for confirmation
    session = SessionLocal()
    try:
        entry = session.execute(
            text("""
                SELECT id, parent_hash, current_hash, timestamp, transaction_payload
                FROM merkle_ledger
                WHERE transaction_payload->>'signed_token' = :token
                ORDER BY id ASC;
            """),
            {"token": token}
        ).fetchall()

        if not entry:
            print("[WARN] Token is mathematically valid, but has NOT been committed to this ledger.")
            return True

        print(f"[OK] Token anchored in {len(entry)} ledger block(s):")
        for e in entry:
            event = e.transaction_payload.get("event", "UNKNOWN")
            status = e.transaction_payload.get("status", "UNKNOWN")
            print(f"     - Block #{e.id} | Event: {event} | Status: {status} | Timestamp: {e.timestamp}")

        return True

    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Artisan Trust-Link Ledger Auditor CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Command: verify-chain
    subparsers.add_parser("verify-chain", help="Audit the entire Merkle ledger from Genesis to tail")

    # Command: verify-token
    token_parser = subparsers.add_parser("verify-token", help="Audit a specific attribution token")
    token_parser.add_argument("--token", required=True, help="Attribution token hex string")
    token_parser.add_argument("--wa-id", required=True, help="WhatsApp ID / Phone number")
    token_parser.add_argument("--inquiry", required=True, help="Original inquiry text string")

    args = parser.parse_args()

    if args.command == "verify-chain":
        valid = audit_chain()
        sys.exit(0 if valid else 1)
    elif args.command == "verify-token":
        valid = audit_token(args.token, args.wa_id, args.inquiry)
        sys.exit(0 if valid else 1)


if __name__ == "__main__":
    main()
