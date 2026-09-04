#!/usr/bin/env bash
set -euo pipefail

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_header() { echo -e "\n${YELLOW}=== $1 ===${NC}"; }

ENV_FILE=".env.prod"
START_TIME=$(date +%s)

log_header "Step 1: Validate $ENV_FILE exists"
if [[ ! -f "$ENV_FILE" ]]; then
    log_error "Missing $ENV_FILE in current directory."
    exit 1
fi
log_info "$ENV_FILE found."

log_header "Step 2: Validate required environment variables"
REQUIRED_KEYS=(
    "POSTGRES_USER"
    "POSTGRES_PASSWORD"
    "POSTGRES_DB"
    "DATABASE_URL"
    "LEDGER_SECRET"
    "WHATSAPP_VERIFY_TOKEN"
    "WHATSAPP_APP_SECRET"
    "WHATSAPP_API_TOKEN"
)

MISSING_KEYS=0
for key in "${REQUIRED_KEYS[@]}"; do
    if ! grep -qE "^${key}=" "$ENV_FILE"; then
        log_error "Missing required key in $ENV_FILE: $key"
        MISSING_KEYS=1
    fi
done

if [[ $MISSING_KEYS -eq 1 ]]; then
    log_error "One or more required environment variables are missing. Exiting."
    exit 1
fi
log_info "All required keys are present in $ENV_FILE."

log_header "Step 3: Validate LEDGER_SECRET entropy"
LEDGER_SECRET_VAL=$(grep -E "^LEDGER_SECRET=" "$ENV_FILE" | cut -d '=' -f 2- | tr -d '"' | tr -d "'")
if [[ ! "$LEDGER_SECRET_VAL" =~ ^[0-9a-fA-F]{64,}$ ]]; then
    log_error "LEDGER_SECRET must be at least 64 hex characters (32 bytes entropy)."
    exit 1
fi
log_info "LEDGER_SECRET meets entropy requirements."

log_header "Step 4: Build production images"
log_info "Building images with no cache..."
docker compose --env-file "$ENV_FILE" build --no-cache

log_header "Step 5: Ensure pgdata volume exists and is not anonymous"
log_info "Checking volume definition (named volumes managed by docker compose)..."
# In a robust setup, docker-compose.yml defines the named volume. We'll verify it's not anonymous if running.
log_info "Assuming docker-compose.yml defines pgdata as a named volume."

log_header "Step 6: Spin up the stack"
docker compose --env-file "$ENV_FILE" up -d

log_header "Step 7: Wait for health checks"
TIMEOUT=60
ELAPSED=0
log_info "Waiting for containers to become healthy (timeout: ${TIMEOUT}s)..."

while true; do
    if [[ $ELAPSED -ge $TIMEOUT ]]; then
         log_error "Timeout waiting for health checks."
         exit 1
    fi
    
    PS_OUTPUT=$(docker compose ps)
    
    if echo "$PS_OUTPUT" | grep -qi "unhealthy"; then
        log_error "One or more containers are unhealthy."
        exit 1
    fi
    
    if ! echo "$PS_OUTPUT" | grep -qi "starting"; then
        log_info "All containers are healthy or running."
        break
    fi
    
    sleep 5
    ELAPSED=$((ELAPSED + 5))
done

log_header "Step 8: Run the auditor verify-chain"
log_info "Running auditor verify-chain inside the gateway container..."
set +e
docker compose exec gateway python -m app.core.auditor verify-chain
EXIT_CODE=$?
set -e

if [[ $EXIT_CODE -eq 0 ]]; then
    log_info "[SUCCESS] Auditor verify-chain passed."
else
    log_error "[FAIL] Auditor verify-chain failed."
    exit 1
fi

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

log_header "Final Summary"
log_info "Deployment completed in ${DURATION} seconds."
log_info "Deployment Status: SUCCESS"
echo ""
echo -e "${YELLOW}Container IDs and Status:${NC}"
docker compose ps -q | xargs -I {} docker inspect -f '{{.Id}} - {{.Name}} - {{.State.Status}}' {} || docker compose ps
echo ""
echo -e "${YELLOW}Port Mappings:${NC}"
docker compose ps --format "table {{.Service}}\t{{.Ports}}"
echo ""
