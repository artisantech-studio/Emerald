import os
import sys
import json
import requests
import psycopg2

DB_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://masterbuilder:secure_ledger_password@localhost:5433/artisan_trust"
)
WEBHOOK_URL = "http://localhost:8000/webhook"

def run_tests():
    print("Running webhook forgery tests...\n")
    
    payload = {"object": "whatsapp_business_account", "entry": []}
    json_payload = json.dumps(payload)
    
    tests_passed = True
    
    # 1. Forged signature
    forged_hash = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    headers = {"X-Hub-Signature-256": f"sha256={forged_hash}"}
    
    try:
        response = requests.post(WEBHOOK_URL, data=json_payload, headers=headers)
        if response.status_code == 401:
            print("✓ Forged signature returned 401 Unauthorized")
        else:
            print(f"✗ Forged signature returned {response.status_code} instead of 401")
            tests_passed = False
    except requests.ConnectionError:
        print("✗ Could not connect to Webhook URL for test 1.")
        tests_passed = False
        
    curl_cmd = f"curl -X POST {WEBHOOK_URL} -H 'X-Hub-Signature-256: sha256={forged_hash}' -H 'Content-Type: application/json' -d '{json_payload}'"
    print(f"  Curl equivalent: {curl_cmd}\n")

    # 2. Missing header
    try:
        response = requests.post(WEBHOOK_URL, data=json_payload)
        if response.status_code == 401:
            print("✓ Missing header returned 401 Unauthorized")
        else:
            print(f"✗ Missing header returned {response.status_code} instead of 401")
            tests_passed = False
    except requests.ConnectionError:
        print("✗ Could not connect to Webhook URL for test 2.")
        tests_passed = False

    # 3. Bad prefix
    headers_bad_prefix = {"X-Hub-Signature-256": f"sha512={forged_hash}"}
    try:
        response = requests.post(WEBHOOK_URL, data=json_payload, headers=headers_bad_prefix)
        if response.status_code == 401:
            print("✓ Bad prefix returned 401 Unauthorized")
        else:
            print(f"✗ Bad prefix returned {response.status_code} instead of 401")
            tests_passed = False
    except requests.ConnectionError:
        print("✗ Could not connect to Webhook URL for test 3.")
        tests_passed = False

    # Database Check
    print("\nChecking database for forged webhook entries...")
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        # Find table with transaction_payload column dynamically
        cur.execute("""
            SELECT table_name 
            FROM information_schema.columns 
            WHERE column_name = 'transaction_payload' AND table_schema = 'public'
            LIMIT 1;
        """)
        row = cur.fetchone()
        
        if row:
            table_name = row[0]
            cur.execute(f"SELECT COUNT(*) FROM {table_name} WHERE transaction_payload->>'event' = 'INBOUND_WHATSAPP_WEBHOOK'")
            count = cur.fetchone()[0]
            if count == 0:
                print(f"✓ Database check passed: 0 forged webhooks recorded in {table_name}.")
            else:
                print(f"✗ Database check failed: {count} webhooks recorded in {table_name}!")
                tests_passed = False
        else:
            # Fallback to guessing a likely table name
            table_name = "transactions"
            cur.execute(f"SELECT COUNT(*) FROM {table_name} WHERE transaction_payload->>'event' = 'INBOUND_WHATSAPP_WEBHOOK'")
            count = cur.fetchone()[0]
            if count == 0:
                print(f"✓ Database check passed: 0 forged webhooks recorded in {table_name}.")
            else:
                print(f"✗ Database check failed: {count} webhooks recorded in {table_name}!")
                tests_passed = False
    except Exception as e:
        print(f"Database check encountered an error: {e}")
        tests_passed = False

    if tests_passed:
        print("\nAll webhook forgery tests passed!")
        sys.exit(0)
    else:
        print("\nSome webhook forgery tests failed.")
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
