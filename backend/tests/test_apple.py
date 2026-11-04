"""Mac builder: registration, hashed tokens, the job queue, one-time job tokens and the error statuses."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import apple, worktrees
from app.api import apple as apple_api
from app.api import deps
from app.api.errors import ApiError, api_error
from app.config import settings
from app.models import AppleHost, AppleJob, AppleJobStatus, Base, Project

NOW = datetime(2030, 1, 1, tzinfo=UTC)
SHA = "a" * 40


@pytest_asyncio.fixture
async def sessions(tmp_path):
    """A real database (a file, so that several sessions can hold the same rows) with the real schema."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'apple.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        s.add(Project(name="P", repo_url="https://github.com/o/r", mode="enterprise", seed=1))
        await s.commit()
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def db(sessions):
    async with sessions() as s:
        yield s


@pytest.fixture(autouse=True)
def apple_mode(monkeypatch):
    monkeypatch.setattr(settings, "apple_mode_enabled", True)


@pytest_asyncio.fixture
async def client(sessions, monkeypatch, tmp_path):
    deps._failures.clear()
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)

    async def per_request_session():
        async with sessions() as s:
            yield s

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error)
    app.include_router(apple_api.admin_router, prefix="/api")
    app.include_router(apple_api.host_router, prefix="/api")
    app.dependency_overrides[deps.get_session] = per_request_session
    async with AsyncClient(transport=ASGITransport(app=app, client=("1.1.1.1", 1)), base_url="http://t") as c:
        yield c
    deps._failures.clear()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(client, name: str = "mac-mini") -> dict:
    r = await client.post("/api/apple-hosts", json={"name": name}, headers=bearer(settings.admin_token))
    assert r.status_code == 201
    return r.json()


async def queue_job(db) -> AppleJob:
    return await apple.enqueue_job(db, 1, "task/1-demo", SHA)


async def claim(client, host_token: str):
    return await client.post("/api/apple-host/claim", headers=bearer(host_token))


async def claimed_job(client, db) -> tuple[AppleJob, dict]:
    host = await register(client)
    job = await queue_job(db)
    body = (await claim(client, host["token"])).json()
    await db.refresh(job)
    return job, body | {"host_token": host["token"]}


async def reload(sessions, model, row_id):
    async with sessions() as s:
        return await s.get(model, row_id)


async def test_registration_returns_the_token_once_and_stores_only_its_hash(client, db):
    host = await register(client)
    assert host["token"].startswith("pmac_") and host["connected"] is False
    stored = await db.get(AppleHost, host["id"])
    assert stored.token_hash == apple.hash_token(host["token"])
    assert host["token"] not in repr(stored.__dict__)
    listed = (await client.get("/api/apple-hosts", headers=bearer(settings.admin_token))).json()
    assert "token" not in listed[0]


async def test_registration_needs_the_raw_admin_token(client):
    r = await client.post("/api/apple-hosts", json={"name": "x"}, headers=bearer("wrong"))
    assert r.status_code == 401


async def test_registration_rejects_a_blank_name(client):
    r = await client.post("/api/apple-hosts", json={"name": "  "}, headers=bearer(settings.admin_token))
    assert r.status_code == 422


async def test_mode_disabled_hides_the_routes(client, monkeypatch):
    monkeypatch.setattr(settings, "apple_mode_enabled", False)
    r = await client.post("/api/apple-host/claim", headers=bearer("pmac_x"))
    assert r.status_code == 404


@pytest.mark.parametrize("token", ["", "garbage", "pmac_unknown"])
async def test_host_routes_refuse_an_invalid_token(client, token):
    assert (await claim(client, token)).status_code == 401


async def test_revoked_host_is_refused(client):
    host = await register(client)
    r = await client.delete(f"/api/apple-hosts/{host['id']}", headers=bearer(settings.admin_token))
    assert r.status_code == 204
    assert (await claim(client, host["token"])).status_code == 401


async def test_revoking_ends_the_running_jobs_and_their_job_tokens(client, sessions, db):
    job, claimed = await claimed_job(client, db)
    r = await client.delete(f"/api/apple-hosts/{(await db.scalar(select(AppleHost.id)))}", headers=bearer(settings.admin_token))
    assert r.status_code == 204
    ended = await reload(sessions, AppleJob, job.id)
    assert ended.status == AppleJobStatus.error and ended.summary == apple.HOST_REVOKED_SUMMARY
    assert ended.job_token_hash is None
    headers = bearer(claimed["job_token"])
    assert (await client.post(f"/api/apple-host/jobs/{job.id}/result", json={"status": "passed"}, headers=headers)).status_code == 401
    assert (await client.get(f"/api/apple-host/jobs/{job.id}/source", headers=headers)).status_code == 401


async def test_revoking_an_unknown_host_is_404(client):
    r = await client.delete("/api/apple-hosts/99", headers=bearer(settings.admin_token))
    assert r.status_code == 404


async def test_revoking_twice_keeps_the_first_date(client, sessions):
    host = await register(client)
    url = f"/api/apple-hosts/{host['id']}"
    await client.delete(url, headers=bearer(settings.admin_token))
    first = (await reload(sessions, AppleHost, host["id"])).revoked_at
    await client.delete(url, headers=bearer(settings.admin_token))
    assert (await reload(sessions, AppleHost, host["id"])).revoked_at == first


async def test_expired_host_token_is_refused(client, db):
    host = await register(client)
    stored = await db.get(AppleHost, host["id"])
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    assert (await claim(client, host["token"])).status_code == 401


async def test_heartbeat_marks_the_host_connected(client):
    host = await register(client)
    assert (await client.post("/api/apple-host/heartbeat", headers=bearer(host["token"]))).status_code == 204
    listed = (await client.get("/api/apple-hosts", headers=bearer(settings.admin_token))).json()
    assert listed[0]["connected"] is True and listed[0]["last_seen_at"] is not None


async def test_claim_without_a_job_is_204(client):
    host = await register(client)
    assert (await claim(client, host["token"])).status_code == 204


async def test_claim_hands_over_the_oldest_job_with_a_hashed_job_token(client, sessions, db):
    host = await register(client)
    first, _second = await queue_job(db), await queue_job(db)
    body = (await claim(client, host["token"])).json()
    assert body["id"] == first.id and body["commit_sha"] == SHA and body["branch"] == "task/1-demo"
    assert body["job_token"].startswith("pjob_")
    stored = await reload(sessions, AppleJob, first.id)
    assert stored.status == AppleJobStatus.running and stored.job_token_hash == apple.hash_token(body["job_token"])
    assert stored.host_id == host["id"] and body["job_token"] not in repr(stored.__dict__)


async def test_claim_respects_the_vm_limit(client, db, monkeypatch):
    monkeypatch.setattr(settings, "apple_max_vms", 1)
    host = await register(client)
    await queue_job(db)
    await queue_job(db)
    assert (await claim(client, host["token"])).status_code == 200
    assert (await claim(client, host["token"])).status_code == 204


async def test_result_stores_the_status_and_the_log_tail(client, sessions, db, monkeypatch):
    monkeypatch.setattr(settings, "apple_log_excerpt_chars", 5)
    job, claimed = await claimed_job(client, db)
    r = await client.post(
        f"/api/apple-host/jobs/{job.id}/result", json={"status": "failed", "log_excerpt": "0123456789"},
        headers=bearer(claimed["job_token"]),
    )
    assert r.status_code == 204
    stored = await reload(sessions, AppleJob, job.id)
    assert stored.status == AppleJobStatus.failed and stored.log_excerpt == "56789" and stored.finished_at is not None


@pytest.mark.parametrize("verdict", ["passed", "failed", "error"])
async def test_each_distinct_status_is_accepted(client, sessions, db, verdict):
    job, claimed = await claimed_job(client, db)
    r = await client.post(
        f"/api/apple-host/jobs/{job.id}/result", json={"status": verdict}, headers=bearer(claimed["job_token"])
    )
    assert r.status_code == 204 and (await reload(sessions, AppleJob, job.id)).status.value == verdict


@pytest.mark.parametrize("verdict", ["queued", "running", "timeout", ""])
async def test_result_refuses_an_unknown_status(client, sessions, db, verdict):
    job, claimed = await claimed_job(client, db)
    r = await client.post(
        f"/api/apple-host/jobs/{job.id}/result", json={"status": verdict}, headers=bearer(claimed["job_token"])
    )
    assert r.status_code == 422 and (await reload(sessions, AppleJob, job.id)).status == AppleJobStatus.running


async def test_a_reused_job_token_is_refused(client, sessions, db):
    job, claimed = await claimed_job(client, db)
    url = f"/api/apple-host/jobs/{job.id}/result"
    assert (await client.post(url, json={"status": "passed"}, headers=bearer(claimed["job_token"]))).status_code == 204
    again = await client.post(url, json={"status": "failed"}, headers=bearer(claimed["job_token"]))
    assert again.status_code == 403 and again.json()["code"] == "apple_job_token_used"
    assert (await reload(sessions, AppleJob, job.id)).status == AppleJobStatus.passed


async def test_two_concurrent_verdicts_with_the_same_job_token_cannot_both_win(client, sessions, db):
    job, _ = await claimed_job(client, db)
    async with sessions() as first, sessions() as second:
        stale_first, stale_second = await first.get(AppleJob, job.id), await second.get(AppleJob, job.id)
        await apple.record_result(first, stale_first, AppleJobStatus.passed, "")
        with pytest.raises(ApiError) as refused:
            await apple.record_result(second, stale_second, AppleJobStatus.failed, "")
    assert refused.value.status_code == 403
    assert (await reload(sessions, AppleJob, job.id)).status == AppleJobStatus.passed


async def test_two_concurrent_source_downloads_cannot_both_win(client, sessions, db):
    job, _ = await claimed_job(client, db)
    async with sessions() as first, sessions() as second:
        stale_first, stale_second = await first.get(AppleJob, job.id), await second.get(AppleJob, job.id)
        await apple.mark_source_downloaded(first, stale_first)
        with pytest.raises(ApiError) as refused:
            await apple.mark_source_downloaded(second, stale_second)
    assert refused.value.status_code == 403


async def test_a_wrong_or_foreign_job_token_is_401(client, db):
    job, claimed = await claimed_job(client, db)
    url = f"/api/apple-host/jobs/{job.id}/result"
    assert (await client.post(url, json={"status": "passed"}, headers=bearer("pjob_wrong"))).status_code == 401
    # The host token is not a job token
    assert (await client.post(url, json={"status": "passed"}, headers=bearer(claimed["host_token"]))).status_code == 401
    unknown = await client.post(
        "/api/apple-host/jobs/99/result", json={"status": "passed"}, headers=bearer(claimed["job_token"])
    )
    assert unknown.status_code == 401


async def test_source_is_a_bundle_served_once(client, db, monkeypatch):
    async def fake_bundle(project, branch: str, commit_sha: str, destination: Path) -> None:
        destination.write_bytes(b"bundle")

    monkeypatch.setattr(worktrees, "bundle_branch", fake_bundle)
    job, claimed = await claimed_job(client, db)
    url = f"/api/apple-host/jobs/{job.id}/source"
    first = await client.get(url, headers=bearer(claimed["job_token"]))
    assert first.status_code == 200 and first.content == b"bundle"
    second = await client.get(url, headers=bearer(claimed["job_token"]))
    assert second.status_code == 403 and second.json()["code"] == "apple_job_token_used"


async def test_overdue_job_ends_as_an_infra_error_and_its_token_is_revoked(client, sessions, db, monkeypatch):
    monkeypatch.setattr(settings, "apple_job_timeout_seconds", 60)
    job, claimed = await claimed_job(client, db)
    host = await db.get(AppleHost, 1)
    host.last_seen_at = apple.as_utc(job.claimed_at) + timedelta(seconds=120)
    await db.commit()
    expired = await apple.expire_overdue_jobs(db, now=apple.as_utc(job.claimed_at) + timedelta(seconds=120))
    assert [e.id for e in expired] == [job.id]
    stored = await reload(sessions, AppleJob, job.id)
    assert stored.status == AppleJobStatus.error and stored.summary == apple.TIMEOUT_SUMMARY
    assert stored.job_token_hash is None
    r = await client.post(
        f"/api/apple-host/jobs/{job.id}/result", json={"status": "passed"}, headers=bearer(claimed["job_token"])
    )
    assert r.status_code == 401


async def test_job_of_a_silent_host_ends_as_an_infra_error(client, sessions, db):
    job, _ = await claimed_job(client, db)
    later = apple.as_utc(job.claimed_at) + timedelta(seconds=settings.apple_heartbeat_timeout_seconds + 1)
    await apple.expire_overdue_jobs(db, now=later)
    stored = await reload(sessions, AppleJob, job.id)
    assert stored.status == AppleJobStatus.error and stored.summary == apple.HOST_LOST_SUMMARY


async def test_live_job_is_left_alone(client, db):
    job, _ = await claimed_job(client, db)
    assert await apple.expire_overdue_jobs(db, now=apple.as_utc(job.claimed_at) + timedelta(seconds=5)) == []
    assert job.status == AppleJobStatus.running


async def test_claim_frees_a_slot_taken_by_a_timed_out_job(client, sessions, db, monkeypatch):
    monkeypatch.setattr(settings, "apple_max_vms", 1)
    monkeypatch.setattr(settings, "apple_job_timeout_seconds", 1)
    host = await register(client)
    stuck = await queue_job(db)
    await queue_job(db)
    assert (await claim(client, host["token"])).status_code == 200
    async with sessions() as s:
        (await s.get(AppleJob, stuck.id)).claimed_at = datetime.now(UTC) - timedelta(seconds=5)
        await s.commit()
    second = (await claim(client, host["token"])).json()
    assert (await reload(sessions, AppleJob, stuck.id)).status == AppleJobStatus.error and second["id"] != stuck.id


async def test_tokens_are_not_logged(client, caplog, db):
    caplog.set_level("DEBUG")
    host = await register(client)
    await queue_job(db)
    claimed = (await claim(client, host["token"])).json()
    await client.post("/api/apple-host/heartbeat", headers=bearer(host["token"]))
    await client.post("/api/apple-host/claim", headers=bearer("pmac_wrong"))
    for secret in (host["token"], claimed["job_token"], "pmac_wrong", settings.admin_token):
        assert secret not in caplog.text


async def test_host_token_is_unique_in_the_database(db):
    _host, token = await apple.create_host(db, "m")
    assert await db.scalar(select(AppleHost).where(AppleHost.token_hash == apple.hash_token(token))) is not None


async def test_claim_sweep_does_not_commit_before_the_claim_ends(client, sessions, db, monkeypatch):
    commits_during_sweep: list[bool] = []
    real_expire = apple.expire_overdue_jobs

    async def spy(s, now=None, *, commit=True):
        commits_during_sweep.append(commit)
        return await real_expire(s, now, commit=commit)

    monkeypatch.setattr(apple, "expire_overdue_jobs", spy)
    host = await register(client)
    await queue_job(db)
    assert (await claim(client, host["token"])).status_code == 200
    assert commits_during_sweep == [False]
