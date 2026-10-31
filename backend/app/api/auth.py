"""Login: exchanges the ADMIN_TOKEN for a short-lived session token."""

from fastapi import APIRouter, Depends

from app.api.deps import require_raw_admin_token
from app.api.schemas import SessionOut
from app.config import settings
from app.sessions import issue_session_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/session", response_model=SessionOut, dependencies=[Depends(require_raw_admin_token)])
async def create_session() -> SessionOut:
    token, expires_at = issue_session_token(settings.admin_token, settings.session_ttl_seconds)
    return SessionOut(token=token, expires_at=expires_at)
