"""Mac builder of the Apple mode: hashed bearer tokens, the build job queue and one-time job tokens."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError, ErrorCode
from app.config import settings
from app.errors import WorkflowError
from app.models import (
    AppleEnrollmentCode,
    AppleHost,
    AppleJob,
    AppleJobStatus,
    Project,
    ProjectPlatform,
    Task,
)

# What a task shows of its build: the lines of the log that look like errors, most recent last
ERROR_LINE_MARKERS = ("error:", "failed", "fatal")
MAX_ERROR_LINES = 20
MAX_ERROR_LINE_CHARS = 300
HOST_TOKEN_PREFIX = "pmac_"
JOB_TOKEN_PREFIX = "pjob_"
ENROLLMENT_CODE_PREFIX = "penr_"
FINAL_STATUSES = (AppleJobStatus.passed, AppleJobStatus.failed, AppleJobStatus.error)
# What the Mac may report: a queued or running status is the server's to set
REPORTABLE_STATUSES = FINAL_STATUSES
TIMEOUT_SUMMARY = "Job timed out"
HOST_LOST_SUMMARY = "Mac builder stopped answering"
HOST_REVOKED_SUMMARY = "Mac builder revoked"
# Arbitrary key of the Postgres advisory lock that serialises job claims (the VM limit is a count across rows)
CLAIM_LOCK_KEY = 550_001


def as_utc(moment: datetime) -> datetime:
    """Timestamps read back from SQLite (tests) are naive: they were stored as UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


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


async def create_enrollment_code(s: AsyncSession, now: datetime | None = None) -> tuple[AppleEnrollmentCode, str]:
    """Generates a one-time enrollment code and returns it with its row; the code is never recoverable afterwards."""
    now = now or datetime.now(UTC)
    await s.execute(delete(AppleEnrollmentCode).where(AppleEnrollmentCode.expires_at <= now))
    code = new_token(ENROLLMENT_CODE_PREFIX)
    row = AppleEnrollmentCode(
        code_hash=hash_token(code), created_at=now,
        expires_at=now + timedelta(seconds=settings.apple_enrollment_code_ttl_seconds),
    )  # fmt: skip
    s.add(row)
    await s.commit()
    return row, code


async def enroll_host(s: AsyncSession, code: str, name: str, now: datetime | None = None) -> tuple[AppleHost, str]:
    """Spends the code and registers the Mac in one transaction; the conditional UPDATE lets only one of two
    concurrent exchanges win. An unknown, expired or spent code is the same 401."""
    now = now or datetime.now(UTC)
    spent = await s.execute(
        update(AppleEnrollmentCode)
        .where(
            AppleEnrollmentCode.code_hash == hash_token(code),
            AppleEnrollmentCode.consumed_at.is_(None),
            AppleEnrollmentCode.expires_at > now,
        )
        .values(consumed_at=now)
    )
    if spent.rowcount == 0:
        await s.rollback()
        raise ApiError(status.HTTP_401_UNAUTHORIZED, ErrorCode.AUTH_INVALID_TOKEN, "Invalid enrollment code")
    return await create_host(s, name, now)


async def authenticate_host(s: AsyncSession, token: str, now: datetime | None = None) -> AppleHost | None:
    """The live (not revoked, not expired) builder owning this token; a successful call counts as seen."""
    now = now or datetime.now(UTC)
    if not token.startswith(HOST_TOKEN_PREFIX):
        return None
    host = await s.scalar(select(AppleHost).where(AppleHost.token_hash == hash_token(token)))
    if host is None or host.revoked_at is not None or as_utc(host.expires_at) <= now:
        return None
    host.last_seen_at = now
    await s.commit()
    return host


def is_connected(host: AppleHost, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    window = timedelta(seconds=settings.apple_heartbeat_timeout_seconds)
    return host.revoked_at is None and host.last_seen_at is not None and now - as_utc(host.last_seen_at) < window


async def has_connected_host(s: AsyncSession, now: datetime | None = None) -> bool:
    """Whether at least one live Mac builder has answered within the heartbeat window."""
    hosts = await s.scalars(select(AppleHost).where(AppleHost.revoked_at.is_(None)))
    return any(is_connected(host, now) for host in hosts)


async def enqueue_job(
    s: AsyncSession, project_id: int, branch: str, commit_sha: str, task_id: int | None = None
) -> AppleJob:
    job = AppleJob(project_id=project_id, branch=branch, commit_sha=commit_sha, task_id=task_id)
    s.add(job)
    await s.commit()
    return job


def _end(job: AppleJob, new_status: AppleJobStatus, summary: str, now: datetime) -> None:
    """Ends a job as an infra failure and revokes its job token."""
    job.status, job.summary, job.finished_at, job.job_token_hash = new_status, summary, now, None


async def expire_overdue_jobs(s: AsyncSession, now: datetime | None = None, *, commit: bool = True) -> list[AppleJob]:
    """Ends the running jobs past their time limit or whose Mac went silent, as infra errors, and revokes their token.

    With commit=False the caller owns the transaction (the claim lock must last until its own commit)."""
    now = now or datetime.now(UTC)
    deadline = now - timedelta(seconds=settings.apple_job_timeout_seconds)
    silence = now - timedelta(seconds=settings.apple_heartbeat_timeout_seconds)
    rows = await s.execute(
        select(AppleJob, AppleHost.last_seen_at)
        .outerjoin(AppleHost, AppleHost.id == AppleJob.host_id)
        .where(AppleJob.status == AppleJobStatus.running)
    )
    expired = []
    for job, last_seen_at in rows.all():
        if job.claimed_at is not None and as_utc(job.claimed_at) <= deadline:
            _end(job, AppleJobStatus.error, TIMEOUT_SUMMARY, now)
        elif last_seen_at is None or as_utc(last_seen_at) <= silence:
            _end(job, AppleJobStatus.error, HOST_LOST_SUMMARY, now)
        else:
            continue
        expired.append(job)
    if expired:
        await (s.commit() if commit else s.flush())
    return expired


async def revoke_host(s: AsyncSession, host: AppleHost, now: datetime | None = None) -> None:
    """Revokes the builder and ends its running jobs as infra errors, so their job tokens stop working too."""
    now = now or datetime.now(UTC)
    if host.revoked_at is None:
        host.revoked_at = now
    running = await s.scalars(
        select(AppleJob).where(AppleJob.host_id == host.id, AppleJob.status == AppleJobStatus.running)
    )
    for job in running:
        _end(job, AppleJobStatus.error, HOST_REVOKED_SUMMARY, now)
    await s.commit()


async def _lock_claims(s: AsyncSession) -> None:
    """Serialises the slot check with the claim on Postgres, held until the commit; SQLite has one writer anyway."""
    if s.get_bind().dialect.name == "postgresql":
        await s.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": CLAIM_LOCK_KEY})


async def claim_job(s: AsyncSession, host: AppleHost, now: datetime | None = None) -> tuple[AppleJob, str] | None:
    """Hands the oldest queued job to the builder with a fresh job token, if fewer than apple_max_vms jobs run."""
    now = now or datetime.now(UTC)
    await _lock_claims(s)
    await expire_overdue_jobs(s, now, commit=False)
    running = await s.scalar(select(func.count()).select_from(AppleJob).where(AppleJob.status == AppleJobStatus.running))
    if running >= settings.apple_max_vms:
        await s.commit()
        return None
    job = await s.scalar(
        select(AppleJob).where(AppleJob.status == AppleJobStatus.queued).order_by(AppleJob.id).limit(1).with_for_update(skip_locked=True)
    )
    if job is None:
        await s.commit()
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
        raise _token_spent()


def _token_spent() -> ApiError:
    return ApiError(status.HTTP_403_FORBIDDEN, ErrorCode.APPLE_JOB_TOKEN_USED, "Job token already used")


async def mark_source_downloaded(s: AsyncSession, job: AppleJob, now: datetime | None = None) -> None:
    """The source is served once per job: the conditional UPDATE lets only one of two concurrent downloads win."""
    claimed = await s.execute(
        update(AppleJob)
        .where(AppleJob.id == job.id, AppleJob.status == AppleJobStatus.running, AppleJob.source_downloaded_at.is_(None))
        .values(source_downloaded_at=now or datetime.now(UTC))
    )
    await s.commit()
    if claimed.rowcount == 0:
        raise _token_spent()


async def record_result(
    s: AsyncSession, job: AppleJob, result: AppleJobStatus, log_excerpt: str, now: datetime | None = None
) -> None:
    """Stores the Mac's verdict and the tail of its log; only one verdict wins, the job token is spent from here on."""
    recorded = await s.execute(
        update(AppleJob)
        .where(AppleJob.id == job.id, AppleJob.status == AppleJobStatus.running)
        .values(
            status=result, summary="", finished_at=now or datetime.now(UTC),
            log_excerpt=log_excerpt[-settings.apple_log_excerpt_chars :],
        )
    )  # fmt: skip
    await s.commit()
    if recorded.rowcount == 0:
        raise _token_spent()


def is_apple_project(project: Project) -> bool:
    return project.platform == ProjectPlatform.apple


async def latest_task_job(s: AsyncSession, task_id: int, commit_sha: str | None = None) -> AppleJob | None:
    """The newest build of the task, of this commit only when one is given."""
    query = select(AppleJob).where(AppleJob.task_id == task_id).order_by(AppleJob.id.desc()).limit(1)
    if commit_sha is not None:
        query = query.where(AppleJob.commit_sha == commit_sha)
    return await s.scalar(query)


async def queue_task_build(s: AsyncSession, project: Project, task: Task, commit_sha: str) -> AppleJob:
    """Queues the build of the task's PR head, once per commit unless the previous one ended in an infra error."""
    existing = await latest_task_job(s, task.id, commit_sha)
    if existing is not None and existing.status != AppleJobStatus.error:
        return existing
    return await enqueue_job(s, project.id, task.branch, commit_sha, task.id)


async def retry_task_build(s: AsyncSession, project: Project, task: Task) -> AppleJob:
    """Relaunches the newest build after an infra error; a build that failed or is still going stays as it is."""
    job = await latest_task_job(s, task.id)
    if job is None or job.status != AppleJobStatus.error:
        raise WorkflowError(
            "Only a build that ended in an infra error can be retried", code=ErrorCode.APPLE_BUILD_NOT_RETRYABLE
        )
    return await enqueue_job(s, project.id, task.branch, job.commit_sha, task.id)


def build_blocker(job: AppleJob | None) -> str | None:
    """Why this build (of the head about to be merged, or None if there is none) prevents the merge."""
    if job is None:
        return "no Swift build for the PR head yet"
    return {
        AppleJobStatus.queued: "Swift build queued",
        AppleJobStatus.running: "Swift build still running",
        AppleJobStatus.failed: "Swift build failed: fix the errors and submit again",
        AppleJobStatus.error: "Swift build hit an infra error, not a test failure: relaunch it with retry_apple_build",
    }.get(job.status)


def error_lines(log_excerpt: str) -> list[str]:
    """The last lines of the log that look like errors; the log is untrusted text, shown as plain text."""
    lines = [line.strip() for line in log_excerpt.splitlines()]
    matching = [line for line in lines if any(marker in line.lower() for marker in ERROR_LINE_MARKERS)]
    return [line[:MAX_ERROR_LINE_CHARS] for line in matching[-MAX_ERROR_LINES:]]


def build_detail(job: AppleJob | None) -> dict | None:
    """A task's build as the API and get_task show it."""
    if job is None:
        return None
    return {
        "job_id": job.id,
        "status": job.status.value,
        "commit_sha": job.commit_sha,
        "infra_error": job.status == AppleJobStatus.error,
        "summary": job.summary,
        "errors": error_lines(job.log_excerpt),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
