import hmac
import hashlib
from fastapi import Request, HTTPException, status
from app.core.config import settings


async def verify_meta_hmac_signature(request: Request) -> bytes:
    """
    Validates the X-Hub-Signature-256 header against the raw request body.
    Returns the cached raw body bytes upon successful authentication.
    """
    signature_header = request.headers.get("X-Hub-Signature-256")
    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing X-Hub-Signature-256 header."
        )

    if not signature_header.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid signature algorithm prefix."
        )

    expected_hash = signature_header.split("sha256=", 1)[1]
    raw_body = await request.body()

    computed_hash = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, expected_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: HMAC verification failed: Signature mismatch."
        )

    return raw_body
