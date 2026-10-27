import secrets
from typing import Annotated, TypeVar

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import Base, get_session

_bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ModelT = TypeVar("ModelT", bound=Base)


async def require_admin(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> None:
    if cred is None or not secrets.compare_digest(cred.credentials, settings.admin_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")


async def get_or_404(s: AsyncSession, model: type[ModelT], id: int, **kwargs) -> ModelT:
    obj = await s.get(model, id, **kwargs)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} {id} not found")
    return obj
