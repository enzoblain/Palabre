"""Mac builder of the Apple mode: hashed bearer tokens, the build job queue and one-time job tokens."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError, ErrorCode
from app.config import settings
from app.models import AppleHost, AppleJob, AppleJobStatus

HOST_TOKEN_PREFIX = "pmac_"
JOB_TOKEN_PREFIX = "pjob_"
FINAL_STATUSES = (AppleJobStatus.passed, AppleJobStatus.failed, AppleJobStatus.error)
# What the Mac may report: a queued or running status is the server's to set
REPORTABLE_STATUSES = FINAL_STATUSES
TIMEOUT_SUMMARY = "Job timed out"
HOST_LOST_SUMMARY = "Mac builder stopped answering"


def hash_token(token: str) -> str:
    """Hex SHA-256: enough for a 256-bit random token, and what the database stores and looks up."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


async def create_host(s: AsyncSession, name: str, now: datetime | None = None) -> tuple[AppleHost, str]:
    """Registers a Mac builder and returns it with its token, which is never recoverable afterwards."""
    now = now or datetime.now(UTC)
    token = new_token(HOST_TOKEN_PREFIX)
    host = AppleHost(
        name=name, token_hash=hash_token(token), created_at=now,
        expires_at=now + timedelta(days=settings.apple_host_token_ttl_days),
    )  # fmt: skip
    s.add(host)
    await s.commit()
    return host, token


async def authenticate_host(s: AsyncSession, token: str, now: datetime | None = None) -> AppleHost | None:
    """The live (not revoked, not expired) builder owning this token; a successful call counts as seen."""
    now = now or datetime.now(UTC)
    if not token.startswith(HOST_TOKEN_PREFIX):
        return None
    host = await s.scalar(select(AppleHost).where(AppleHost.token_hash == hash_token(token)))
    if host is None or host.revoked_at is not None or host.expires_at <= now:
        return None
    host.last_seen_at = now
    await s.commit()
    return host


def is_connected(host: AppleHost, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    window = timedelta(seconds=settings.apple_heartbeat_timeout_seconds)
    return host.revoked_at is None and host.last_seen_at is not None and now - host.last_seen_at < window


async def enqueue_job(s: AsyncSession, project_id: int, branch: str, commit_sha: str) -> AppleJob:
    job = AppleJob(project_id=project_id, branch=branch, commit_sha=commit_sha)
    s.add(job)
    await s.commit()
    return job


def _end(job: AppleJob, status_: AppleJobStatus, summary: str, now: datetime) -> None:
    job.status, job.summary, job.finished_at = status_, summary, now


async def expire_overdue_jobs(s: AsyncSession, now: datetime | None = None) -> list[AppleJob]:
    """Ends the running jobs past their time limit or whose Mac went silent, as infra errors, and revokes their token."""
    now = now or datetime.now(UTC)
    deadline = now - timedelta(seconds=settings.apple_job_timeout_seconds)
    silence = now - timedelta(seconds=settings.apple_heartbeat_timeout_seconds)
    running = await s.scalars(select(AppleJob).where(AppleJob.status == AppleJobStatus.running))
    expired = []
    for job in running:
        host = await s.get(AppleHost, job.host_id) if job.host_id else None
        if job.claimed_at is not None and job.claimed_at <= deadline:
            _end(job, AppleJobStatus.error, TIMEOUT_SUMMARY, now)
        elif host is None or host.last_seen_at is None or host.last_seen_at <= silence:
            _end(job, AppleJobStatus.error, HOST_LOST_SUMMARY, now)
        else:
            continue
        job.job_token_hash = None
        expired.append(job)
    if expired:
        await s.commit()
    return expired


async def claim_job(s: AsyncSession, host: AppleHost, now: datetime | None = None) -> tuple[AppleJob, str] | None:
    """Hands the oldest queued job to the builder with a fresh job token, if fewer than apple_max_vms jobs run."""
    now = now or datetime.now(UTC)
    await expire_overdue_jobs(s, now)
    running = await s.scalar(select(func.count()).select_from(AppleJob).where(AppleJob.status == AppleJobStatus.running))
    if running >= settings.apple_max_vms:
        return None
    job = await s.scalar(
        select(AppleJob).where(AppleJob.status == AppleJobStatus.queued).order_by(AppleJob.id).limit(1).with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    token = new_token(JOB_TOKEN_PREFIX)
    job.status, job.host_id, job.claimed_at, job.job_token_hash = AppleJobStatus.running, host.id, now, hash_token(token)
    await s.commit()
    return job, token


def check_job_token(job: AppleJob, token: str) -> None:
    """401 for a token that is not this job's or was revoked, 403 once the job is over (the token was spent)."""
    if job.job_token_hash is None or not hmac.compare_digest(job.job_token_hash, hash_token(token)):
        raise ApiError(status.HTTP_401_UNAUTHORIZED, ErrorCode.AUTH_INVALID_TOKEN, "Invalid token")
    if job.status in FINAL_STATUSES:
        raise ApiError(status.HTTP_403_FORBIDDEN, ErrorCode.APPLE_JOB_TOKEN_USED, "Job token already used")


async def mark_source_downloaded(s: AsyncSession, job: AppleJob, now: datetime | None = None) -> None:
    """The source is served once per job: a second download with the same token is refused."""
    if job.source_downloaded_at is not None:
        raise ApiError(status.HTTP_403_FORBIDDEN, ErrorCode.APPLE_JOB_TOKEN_USED, "Source already downloaded")
    job.source_downloaded_at = now or datetime.now(UTC)
    await s.commit()


async def record_result(
    s: AsyncSession, job: AppleJob, result: AppleJobStatus, log_excerpt: str, now: datetime | None = None
) -> None:
    """Stores the Mac's verdict and the tail of its log; the job token is spent from here on."""
    tail = log_excerpt[-settings.apple_log_excerpt_chars :]
    _end(job, result, "", now or datetime.now(UTC))
    job.log_excerpt = tail
    await s.commit()
