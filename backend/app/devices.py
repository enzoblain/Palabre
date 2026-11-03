"""Per-device sessions for the mobile app: opaque "pdev_" tokens, stored as HMAC-SHA256 and revoked by deleting the row."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeviceSession

TOKEN_PREFIX = "pdev_"
# Domain separation: the storage key is never the raw ADMIN_TOKEN nor the web signing key
_KEY_LABEL = b"palabre-device-v1"
# The app polls every 2 s: the expiry slides, but is written at most once per this interval
TOUCH_INTERVAL = timedelta(minutes=1)


def _hash_key(admin_token: str) -> bytes:
    return hmac.new(admin_token.encode(), _KEY_LABEL, hashlib.sha256).digest()


def hash_device_token(admin_token: str, token: str) -> str:
    """Hex HMAC-SHA256 of the token: what the database stores and looks up."""
    return hmac.new(_hash_key(admin_token), token.encode(), hashlib.sha256).hexdigest()


def looks_like_device_token(token: str) -> bool:
    return token.startswith(TOKEN_PREFIX)


async def create_device_session(
    s: AsyncSession, admin_token: str, name: str, ttl_seconds: int, now: datetime | None = None
) -> tuple[DeviceSession, str]:
    """Stores a new device and returns it with its token, which is never recoverable afterwards."""
    now = now or datetime.now(UTC)
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    device = DeviceSession(
        name=name,
        token_hash=hash_device_token(admin_token, token),
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    s.add(device)
    await s.commit()
    return device, token


async def authenticate_device(
    s: AsyncSession, admin_token: str, token: str, ttl_seconds: int, now: datetime | None = None
) -> bool:
    """True if the token belongs to a live device. Checked on every request; use slides the expiry (throttled)."""
    now = now or datetime.now(UTC)
    token_hash = hash_device_token(admin_token, token)
    device = await s.scalar(select(DeviceSession).where(DeviceSession.token_hash == token_hash))
    # The lookup by HMAC is the real protection; the digest comparison is only a sanity check
    if device is None or not hmac.compare_digest(device.token_hash, token_hash):
        return False
    # Statements by id, not ORM flushes: a device revoked meanwhile must not raise StaleDataError (500)
    if device.expires_at <= now:
        await s.execute(delete(DeviceSession).where(DeviceSession.id == device.id))
        await s.commit()
        return False
    if now - device.last_used_at >= TOUCH_INTERVAL:
        touched = await s.execute(
            update(DeviceSession)
            .where(DeviceSession.id == device.id)
            .values(last_used_at=now, expires_at=now + timedelta(seconds=ttl_seconds))
        )
        await s.commit()
        return touched.rowcount > 0
    return True
