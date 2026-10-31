"""Stateless admin session tokens: "<expires_at>.<signature>", signed with a key derived from ADMIN_TOKEN."""

import base64
import hashlib
import hmac
import time

# Domain separation: the signing key is never the raw ADMIN_TOKEN
_KEY_LABEL = b"palabre-session-v1"
# Unix seconds fit in far fewer digits; the cap keeps int() away from huge inputs
_MAX_EXPIRY_DIGITS = 12


def _signing_key(admin_token: str) -> bytes:
    return hmac.new(admin_token.encode(), _KEY_LABEL, hashlib.sha256).digest()


def _sign(admin_token: str, expires_at: int) -> str:
    digest = hmac.new(_signing_key(admin_token), str(expires_at).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def issue_session_token(admin_token: str, ttl_seconds: int, now: float | None = None) -> tuple[str, int]:
    """A signed token valid for ttl_seconds, and its expiry (Unix seconds)."""
    expires_at = int((time.time() if now is None else now) + ttl_seconds)
    return f"{expires_at}.{_sign(admin_token, expires_at)}", expires_at


def verify_session_token(admin_token: str, token: str, now: float | None = None) -> bool:
    """True if the token is well formed, signed with the current ADMIN_TOKEN and not expired."""
    expiry, _, signature = token.partition(".")
    if not (expiry.isascii() and expiry.isdecimal()) or len(expiry) > _MAX_EXPIRY_DIGITS or not signature:
        return False
    if expiry != str(int(expiry)):  # canonical form only: no leading zeros, one string per token
        return False
    if not hmac.compare_digest(signature.encode(), _sign(admin_token, int(expiry)).encode()):
        return False
    return int(expiry) > (time.time() if now is None else now)
