"""
Artisan Trust-Link Gateway — Production Gunicorn Configuration
Optimized for a standard 2–4 core VPS or mobile workstation.
"""
import multiprocessing

# ─── Worker Configuration ────────────────────────────────────────────
# Formula: (2 * CPU cores) + 1, capped at 4 for memory safety on small VPS
workers = min((2 * multiprocessing.cpu_count()) + 1, 4)
worker_class = "uvicorn.workers.UvicornWorker"

# ─── Timeouts ────────────────────────────────────────────────────────
# 120s: Prevents hanging on slow webhook deliveries from Meta's servers.
# If a worker is silent for this long, Gunicorn kills and replaces it.
timeout = 120

# Graceful shutdown window: allows in-flight Merkle writes to commit
# before the worker is force-killed.
graceful_timeout = 30

# Keep-alive for HTTP/1.1 persistent connections (seconds)
keepalive = 5

# ─── Binding ─────────────────────────────────────────────────────────
bind = "0.0.0.0:8000"

# ─── Logging ─────────────────────────────────────────────────────────
# Log to stdout/stderr for Docker log aggregation
accesslog = "-"
errorlog = "-"
loglevel = "info"

# ─── Process Naming ──────────────────────────────────────────────────
proc_name = "artisan_gateway"

# ─── Security ────────────────────────────────────────────────────────
# Limit request sizes to prevent abuse (10 MB max)
limit_request_body = 10485760
# Limit header field size (8 KB)
limit_request_field_size = 8190
