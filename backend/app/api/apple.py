"""REST endpoints of the Apple mode: the Mac builders' admin side and the API the Mac itself calls."""

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app import apple, worktrees
from app.api.deps import SessionDep, authentication_failure, check_lockout_for, get_or_404, require_admin, require_raw_admin_token
from app.api.errors import ApiError, ErrorCode
from app.api.schemas import AppleHostCreate, AppleHostOut, AppleHostTokenOut, AppleJobClaim, AppleJobResult
from app.config import settings
from app.models import AppleHost, AppleJob, AppleJobStatus, Project

_bearer = HTTPBearer(auto_error=False)


async def require_apple_mode() -> None:
    if not settings.apple_mode_enabled:
        raise ApiError(status.HTTP_404_NOT_FOUND, ErrorCode.NOT_FOUND, "Not found")


admin_router = APIRouter(tags=["apple"], dependencies=[Depends(require_apple_mode)])
host_router = APIRouter(prefix="/apple-host", tags=["apple-host"], dependencies=[Depends(require_apple_mode)])


def _host_out(host: AppleHost) -> AppleHostOut:
    return AppleHostOut(
        id=host.id, name=host.name, created_at=host.created_at, expires_at=host.expires_at,
        last_seen_at=host.last_seen_at, revoked_at=host.revoked_at, connected=apple.is_connected(host),
    )  # fmt: skip


@admin_router.post(
    "/apple-hosts", response_model=AppleHostTokenOut, status_code=201, dependencies=[Depends(require_raw_admin_token)]
)
async def register_host(body: AppleHostCreate, s: SessionDep) -> AppleHostTokenOut:
    """Registers a Mac builder; its token is in this answer only. Needs the raw ADMIN_TOKEN."""
    host, token = await apple.create_host(s, body.name)
    return AppleHostTokenOut(**_host_out(host).model_dump(), token=token)


@admin_router.get("/apple-hosts", response_model=list[AppleHostOut], dependencies=[Depends(require_admin)])
async def list_hosts(s: SessionDep) -> list[AppleHostOut]:
    """The registered Macs with their connection state (seen within the heartbeat timeout)."""
    return [_host_out(host) for host in await s.scalars(select(AppleHost).order_by(AppleHost.id))]


@admin_router.delete("/apple-hosts/{host_id}", status_code=204, dependencies=[Depends(require_admin)])
async def revoke_host(host_id: int, s: SessionDep) -> Response:
    """Revokes the token: the Mac's next call is a 401. Revoking twice keeps the first date."""
    host = await get_or_404(s, AppleHost, host_id)
    if host.revoked_at is None:
        host.revoked_at = datetime.now(UTC)
        await s.commit()
    return Response(status_code=204)


async def _token(request: Request, cred: HTTPAuthorizationCredentials | None) -> str:
    await check_lockout_for(request)
    return cred.credentials if cred else ""


async def current_host(
    request: Request, s: SessionDep, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> AppleHost:
    host = await apple.authenticate_host(s, await _token(request, cred))
    if host is None:
        raise await authentication_failure(request)
    return host


async def current_job(
    job_id: int, request: Request, s: SessionDep, cred: HTTPAuthorizationCredentials | None = Depends(_bearer)
) -> AppleJob:
    """The job addressed by the URL, if the bearer is its job token."""
    token = await _token(request, cred)
    job = await s.get(AppleJob, job_id)
    if job is None or not token.startswith(apple.JOB_TOKEN_PREFIX):
        raise await authentication_failure(request)
    try:
        apple.check_job_token(job, token)
    except ApiError as error:
        if error.status_code == status.HTTP_401_UNAUTHORIZED:
            raise await authentication_failure(request) from error
        raise
    return job


@host_router.post("/heartbeat", status_code=204)
async def heartbeat(_host: AppleHost = Depends(current_host)) -> Response:
    """Authenticating already records the Mac as seen."""
    return Response(status_code=204)


@host_router.post("/claim", response_model=AppleJobClaim, responses={204: {"description": "No job to run"}})
async def claim_job(s: SessionDep, host: AppleHost = Depends(current_host)):
    """Hands the Mac its next job, with the job token for it; 204 when none is queued or all VM slots are busy."""
    claimed = await apple.claim_job(s, host)
    if claimed is None:
        return Response(status_code=204)
    job, token = claimed
    return AppleJobClaim(
        id=job.id, project_id=job.project_id, branch=job.branch, commit_sha=job.commit_sha, job_token=token,
        source_url=f"/api/apple-host/jobs/{job.id}/source",
    )  # fmt: skip


def _remove(path: Path) -> None:
    path.unlink(missing_ok=True)


@host_router.get("/jobs/{job_id}/source", response_class=FileResponse)
async def download_source(job_id: int, s: SessionDep, background: BackgroundTasks, job: AppleJob = Depends(current_job)):
    """The job's code as a git bundle, once per job token."""
    project = await get_or_404(s, Project, job.project_id)
    await apple.mark_source_downloaded(s, job)
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=settings.runtime_dir, suffix=".bundle", delete=False) as handle:
        bundle = Path(handle.name)
    background.add_task(_remove, bundle)
    try:
        await worktrees.bundle_branch(project, job.branch, job.commit_sha, bundle)
    except Exception:
        await asyncio.to_thread(_remove, bundle)
        raise
    return FileResponse(bundle, media_type="application/octet-stream", filename=f"job-{job_id}.bundle")


@host_router.post("/jobs/{job_id}/result", status_code=204)
async def post_result(job_id: int, body: AppleJobResult, s: SessionDep, job: AppleJob = Depends(current_job)) -> Response:
    """The Mac's verdict and log tail; spends the job token."""
    await apple.record_result(s, job, AppleJobStatus(body.status), body.log_excerpt)
    return Response(status_code=204)
