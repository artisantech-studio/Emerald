#!/usr/bin/env python3
"""
Ward 1 concurrency stress test for the Artisan Trust-Link Gateway's Merkle ledger.
"""
import asyncio
import aiohttp
import argparse
import os
import sys
import time
import uuid
import psycopg2
from psycopg2.extras import DictCursor

def get_db_connection():
    db_url = os.environ.get(
        "DATABASE_URL", 
        "postgresql://masterbuilder:secure_ledger_password@localhost:5433/artisan_trust"
    )
    return psycopg2.connect(db_url)

def truncate_ledger():
    try:
        print("Truncating ledger...")
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE merkle_ledger RESTART IDENTITY CASCADE;")
            conn.commit()
            print("Ledger truncated successfully.")
    except Exception as e:
        print(f"Error truncating ledger: {e}")
        sys.exit(1)
        
async def make_request(session, url, index):
    payload = {
        "broker_id": str(uuid.uuid4()),
        "merchant_phone": f"+1555{index:06d}",
        "wa_id": str(uuid.uuid4()),
        "inquiry_text": f"Stress test inquiry {index}"
    }
    
    start_time = time.time()
    try:
        async with session.post(url, json=payload) as response:
            status = response.status
            await response.read() 
            duration = time.time() - start_time
            return {"status": status, "duration": duration, "error": None}
    except Exception as e:
        duration = time.time() - start_time
        return {"status": None, "duration": duration, "error": str(e)}

async def run_stress_test(gateway_url, concurrency):
    url = f"{gateway_url.rstrip('/')}/v1/referral/sign"
    print(f"Starting {concurrency} concurrent requests to {url}...")
    
    start_time = time.time()
    async with aiohttp.ClientSession() as session:
        tasks = [make_request(session, url, i) for i in range(concurrency)]
        results = await asyncio.gather(*tasks)
        
    total_duration = time.time() - start_time
    return results, total_duration

def verify_ledger(expected_new_blocks):
    print("Verifying ledger state...")
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=DictCursor) as cur:
                cur.execute("SELECT id, parent_hash, current_hash FROM merkle_ledger ORDER BY id ASC")
                blocks = cur.fetchall()
    except Exception as e:
        print(f"Error querying ledger: {e}")
        return False, f"Database error: {e}"

    if not blocks:
        return False, "Ledger is empty."
        
    # e. Block[0].parent_hash is None (Genesis)
    if blocks[0]['parent_hash'] is not None:
        return False, f"Genesis block (id={blocks[0]['id']}) has non-null parent_hash: {blocks[0]['parent_hash']}"
        
    # c. No two blocks share the same parent_hash (use a set, check len == number of blocks)
    parent_hashes = set(b['parent_hash'] for b in blocks)
    if len(parent_hashes) != len(blocks):
        return False, f"Duplicate parent_hashes detected! Unique parent hashes: {len(parent_hashes)}, Total blocks: {len(blocks)}"
    
    # d. Every block[i].parent_hash == block[i-1].current_hash (strict linear sequence)
    for i in range(1, len(blocks)):
        phash = blocks[i]['parent_hash']
        prev_chash = blocks[i-1]['current_hash']
        if phash != prev_chash:
            return False, f"Broken chain at block index {i} (id={blocks[i]['id']}): parent_hash {phash} != prev block current_hash {prev_chash}"
            
    return True, f"Verified {len(blocks)} blocks in the ledger. Chain is strictly linear and valid."

def main():
    parser = argparse.ArgumentParser(description="Concurrency stress test for Artisan Trust-Link Gateway")
    parser.add_argument("--gateway-url", default="http://localhost:8000", help="Gateway URL")
    parser.add_argument("--concurrency", type=int, default=50, help="Number of concurrent requests")
    parser.add_argument("--truncate", action="store_true", help="Truncate ledger before testing")
    args = parser.parse_args()
    
    if args.truncate:
        db_url = os.environ.get("DATABASE_URL", "")
        env_is_prod = os.environ.get("ENV", "").lower() in ("prod", "production")
        url_is_prod = not any(local in args.gateway_url for local in ("localhost", "127.0.0.1", "0.0.0.0"))
        db_is_prod = db_url and not any(local in db_url for local in ("localhost", "127.0.0.1", "0.0.0.0"))
        
        if env_is_prod or url_is_prod or db_is_prod:
            print("FATAL ERROR: --truncate is strictly forbidden against production database or URL.")
            sys.exit(1)
        truncate_ledger()
        
    # Run requests
    results, total_duration = asyncio.run(run_stress_test(args.gateway_url, args.concurrency))
    
    # Analyze results
    success_count = sum(1 for r in results if r['status'] == 201)
    fail_count = args.concurrency - success_count
    durations = [r['duration'] for r in results]
    avg_duration = sum(durations) / len(durations) if durations else 0
    
    print("\n--- Test Results ---")
    print(f"Total Duration: {total_duration:.4f}s")
    print(f"Avg Request Duration: {avg_duration:.4f}s")
    print(f"HTTP 201 Responses: {success_count}/{args.concurrency}")
    if fail_count > 0:
        errors = [r for r in results if r['status'] != 201]
        print(f"Failed/Error Responses: {len(errors)}")
        for e in errors[:5]:
            print(f"  Status: {e.get('status')} - Error: {e.get('error')}")
            
    # Verify Ledger
    is_valid, msg = verify_ledger(args.concurrency)
    
    print("\n--- Ledger Verification ---")
    print(msg)
    
    # Final Verdict
    print("\n--- Final Verdict ---")
    # a. ALL requests returned HTTP 201
    passed = (success_count == args.concurrency) and is_valid
    if passed:
        print("PASS")
        sys.exit(0)
    else:
        print("FAIL")
        sys.exit(1)

if __name__ == "__main__":
    main()
