"""Login: exchanges the ADMIN_TOKEN for a short-lived session token, and manages the mobile device sessions."""

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import SessionDep, get_or_404, require_admin, require_raw_admin_token
from app.api.schemas import DeviceCreate, DeviceOut, DeviceTokenOut, SessionOut
from app.config import settings
from app.devices import create_device_session
from app.models import DeviceSession
from app.sessions import issue_session_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/session", response_model=SessionOut, dependencies=[Depends(require_raw_admin_token)])
async def create_session() -> SessionOut:
    token, expires_at = issue_session_token(settings.admin_token, settings.session_ttl_seconds)
    return SessionOut(token=token, expires_at=expires_at)


@router.post("/devices", response_model=DeviceTokenOut, status_code=201, dependencies=[Depends(require_raw_admin_token)])
async def pair_device(body: DeviceCreate, s: SessionDep) -> DeviceTokenOut:
    """Pairs a phone: the raw ADMIN_TOKEN is the access code; the device token is returned this once."""
    device, token = await create_device_session(s, settings.admin_token, body.name, settings.device_session_ttl_seconds)
    return DeviceTokenOut(**DeviceOut.model_validate(device).model_dump(), token=token)


@router.get("/devices", response_model=list[DeviceOut], dependencies=[Depends(require_admin)])
async def list_devices(s: SessionDep) -> list[DeviceSession]:
    return list((await s.scalars(select(DeviceSession).order_by(DeviceSession.created_at.desc(), DeviceSession.id.desc()))).all())


@router.delete("/devices/{device_id}", status_code=204, dependencies=[Depends(require_admin)])
async def revoke_device(device_id: int, s: SessionDep) -> None:
    device = await get_or_404(s, DeviceSession, device_id)
    await s.delete(device)
    await s.commit()
