"""Mac builder: registration, hashed tokens, the job queue, one-time job tokens and the error statuses."""

from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import apple, worktrees
from app.api import apple as apple_api
from app.api import deps
from app.api.errors import ApiError, api_error
from app.config import settings
from app.models import AppleHost, AppleJob, AppleJobStatus, Project

NOW = datetime(2030, 1, 1, tzinfo=UTC)
SHA = "a" * 40


class FakeStore:
    def __init__(self) -> None:
        self.hosts: list[AppleHost] = []
        self.jobs: list[AppleJob] = []
        self.ids = count(1)
        self.commits = 0


class FakeSession:
    """Just enough of AsyncSession for apple.py: rows live in the shared store, queries are matched by their shape."""

    def __init__(self, store: FakeStore) -> None:
        self.store = store

    def add(self, row) -> None:
        row.id = next(self.store.ids)
        row.status = getattr(row, "status", None) or (AppleJobStatus.queued if isinstance(row, AppleJob) else None)
        for field in ("summary", "log_excerpt"):
            if isinstance(row, AppleJob) and getattr(row, field) is None:
                setattr(row, field, "")
        (self.store.jobs if isinstance(row, AppleJob) else self.store.hosts).append(row)

    async def commit(self) -> None:
        self.store.commits += 1

    async def get(self, model, row_id):
        rows = {AppleHost: self.store.hosts, AppleJob: self.store.jobs}.get(model, [])
        if model is Project:
            return SimpleProject() if row_id == 1 else None
        return next((r for r in rows if r.id == row_id), None)

    async def scalar(self, query):
        sql = str(query)
        if "FROM apple_hosts" in sql:
            wanted = next(iter(query.compile().params.values()))
            return next((h for h in self.store.hosts if h.token_hash == wanted), None)
        if "count(" in sql:
            return sum(1 for j in self.store.jobs if j.status == AppleJobStatus.running)
        queued = sorted((j for j in self.store.jobs if j.status == AppleJobStatus.queued), key=lambda j: j.id)
        return queued[0] if queued else None

    async def scalars(self, query):
        if "FROM apple_hosts" in str(query):
            return list(self.store.hosts)
        return [j for j in self.store.jobs if j.status == AppleJobStatus.running]


class SimpleProject:
    id = 1


@pytest.fixture
def store():
    return FakeStore()


@pytest.fixture(autouse=True)
def apple_mode(monkeypatch):
    monkeypatch.setattr(settings, "apple_mode_enabled", True)


@pytest_asyncio.fixture
async def client(store, monkeypatch, tmp_path):
    deps._failures.clear()
    monkeypatch.setattr(settings, "runtime_dir", tmp_path)
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error)
    app.include_router(apple_api.admin_router, prefix="/api")
    app.include_router(apple_api.host_router, prefix="/api")
    app.dependency_overrides[deps.get_session] = lambda: FakeSession(store)
    async with AsyncClient(transport=ASGITransport(app=app, client=("1.1.1.1", 1)), base_url="http://t") as c:
        yield c
    deps._failures.clear()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(client, name: str = "mac-mini") -> dict:
    r = await client.post("/api/apple-hosts", json={"name": name}, headers=bearer(settings.admin_token))
    assert r.status_code == 201
    return r.json()


async def queue_job(store) -> AppleJob:
    return await apple.enqueue_job(FakeSession(store), 1, "task/1-demo", SHA)


async def claim(client, host_token: str):
    return await client.post("/api/apple-host/claim", headers=bearer(host_token))


async def test_registration_returns_the_token_once_and_stores_only_its_hash(client, store):
    host = await register(client)
    assert host["token"].startswith("pmac_") and host["connected"] is False
    assert store.hosts[0].token_hash == apple.hash_token(host["token"])
    assert host["token"] not in repr(store.hosts[0].__dict__)
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


async def test_revoked_host_is_refused(client, store):
    host = await register(client)
    r = await client.delete(f"/api/apple-hosts/{store.hosts[0].id}", headers=bearer(settings.admin_token))
    assert r.status_code == 204
    assert (await claim(client, host["token"])).status_code == 401


async def test_revoking_an_unknown_host_is_404(client):
    r = await client.delete("/api/apple-hosts/99", headers=bearer(settings.admin_token))
    assert r.status_code == 404


async def test_expired_host_token_is_refused(client, store):
    host = await register(client)
    store.hosts[0].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert (await claim(client, host["token"])).status_code == 401


async def test_heartbeat_marks_the_host_connected(client):
    host = await register(client)
    assert (await client.post("/api/apple-host/heartbeat", headers=bearer(host["token"]))).status_code == 204
    listed = (await client.get("/api/apple-hosts", headers=bearer(settings.admin_token))).json()
    assert listed[0]["connected"] is True and listed[0]["last_seen_at"] is not None


async def test_claim_without_a_job_is_204(client):
    host = await register(client)
    assert (await claim(client, host["token"])).status_code == 204


async def test_claim_hands_over_the_oldest_job_with_a_hashed_job_token(client, store):
    host = await register(client)
    first, _second = await queue_job(store), await queue_job(store)
    body = (await claim(client, host["token"])).json()
    assert body["id"] == first.id and body["commit_sha"] == SHA and body["branch"] == "task/1-demo"
    assert body["job_token"].startswith("pjob_")
    assert first.status == AppleJobStatus.running and first.job_token_hash == apple.hash_token(body["job_token"])
    assert body["job_token"] not in repr(first.__dict__)


async def test_claim_respects_the_vm_limit(client, store, monkeypatch):
    monkeypatch.setattr(settings, "apple_max_vms", 1)
    host = await register(client)
    await queue_job(store)
    await queue_job(store)
    assert (await claim(client, host["token"])).status_code == 200
    assert (await claim(client, host["token"])).status_code == 204


async def claimed_job(client, store) -> tuple[AppleJob, dict]:
    host = await register(client)
    await queue_job(store)
    body = (await claim(client, host["token"])).json()
    return store.jobs[0], body


async def test_result_stores_the_status_and_the_log_tail(client, store, monkeypatch):
    monkeypatch.setattr(settings, "apple_log_excerpt_chars", 5)
    job, claimed = await claimed_job(client, store)
    r = await client.post(
        f"/api/apple-host/jobs/{job.id}/result", json={"status": "failed", "log_excerpt": "0123456789"},
        headers=bearer(claimed["job_token"]),
    )
    assert r.status_code == 204
    assert job.status == AppleJobStatus.failed and job.log_excerpt == "56789" and job.finished_at is not None


@pytest.mark.parametrize("verdict", ["passed", "failed", "error"])
async def test_each_distinct_status_is_accepted(client, store, verdict):
    job, claimed = await claimed_job(client, store)
    r = await client.post(
        f"/api/apple-host/jobs/{job.id}/result", json={"status": verdict}, headers=bearer(claimed["job_token"])
    )
    assert r.status_code == 204 and job.status.value == verdict


@pytest.mark.parametrize("verdict", ["queued", "running", "timeout", ""])
async def test_result_refuses_an_unknown_status(client, store, verdict):
    job, claimed = await claimed_job(client, store)
    r = await client.post(
        f"/api/apple-host/jobs/{job.id}/result", json={"status": verdict}, headers=bearer(claimed["job_token"])
    )
    assert r.status_code == 422 and job.status == AppleJobStatus.running


async def test_a_reused_job_token_is_refused(client, store):
    job, claimed = await claimed_job(client, store)
    url = f"/api/apple-host/jobs/{job.id}/result"
    assert (await client.post(url, json={"status": "passed"}, headers=bearer(claimed["job_token"]))).status_code == 204
    again = await client.post(url, json={"status": "failed"}, headers=bearer(claimed["job_token"]))
    assert again.status_code == 403 and again.json()["code"] == "apple_job_token_used"
    assert job.status == AppleJobStatus.passed


async def test_a_wrong_or_foreign_job_token_is_401(client, store):
    job, claimed = await claimed_job(client, store)
    url = f"/api/apple-host/jobs/{job.id}/result"
    assert (await client.post(url, json={"status": "passed"}, headers=bearer("pjob_wrong"))).status_code == 401
    # The host token is not a job token
    host_token = next(iter(store.hosts)).token_hash
    assert (await client.post(url, json={"status": "passed"}, headers=bearer(host_token))).status_code == 401
    assert (await client.post("/api/apple-host/jobs/99/result", json={"status": "passed"}, headers=bearer(claimed["job_token"]))).status_code == 401


async def test_source_is_a_bundle_served_once(client, store, monkeypatch):
    async def fake_bundle(project, branch: str, commit_sha: str, destination: Path) -> None:
        destination.write_bytes(b"bundle")

    monkeypatch.setattr(worktrees, "bundle_branch", fake_bundle)
    job, claimed = await claimed_job(client, store)
    url = f"/api/apple-host/jobs/{job.id}/source"
    first = await client.get(url, headers=bearer(claimed["job_token"]))
    assert first.status_code == 200 and first.content == b"bundle"
    second = await client.get(url, headers=bearer(claimed["job_token"]))
    assert second.status_code == 403 and second.json()["code"] == "apple_job_token_used"


async def test_overdue_job_ends_as_an_infra_error_and_its_token_is_revoked(client, store, monkeypatch):
    monkeypatch.setattr(settings, "apple_job_timeout_seconds", 60)
    job, claimed = await claimed_job(client, store)
    store.hosts[0].last_seen_at = NOW + timedelta(seconds=120)
    expired = await apple.expire_overdue_jobs(FakeSession(store), now=NOW + timedelta(seconds=120))
    assert expired == [job] and job.status == AppleJobStatus.error and job.summary == apple.TIMEOUT_SUMMARY
    assert job.job_token_hash is None
    r = await client.post(
        f"/api/apple-host/jobs/{job.id}/result", json={"status": "passed"}, headers=bearer(claimed["job_token"])
    )
    assert r.status_code == 401


async def test_job_of_a_silent_host_ends_as_an_infra_error(client, store):
    job, _ = await claimed_job(client, store)
    job.claimed_at = NOW
    store.hosts[0].last_seen_at = NOW
    later = NOW + timedelta(seconds=settings.apple_heartbeat_timeout_seconds + 1)
    await apple.expire_overdue_jobs(FakeSession(store), now=later)
    assert job.status == AppleJobStatus.error and job.summary == apple.HOST_LOST_SUMMARY


async def test_live_job_is_left_alone(client, store):
    job, _ = await claimed_job(client, store)
    job.claimed_at = NOW
    store.hosts[0].last_seen_at = NOW + timedelta(seconds=5)
    assert await apple.expire_overdue_jobs(FakeSession(store), now=NOW + timedelta(seconds=10)) == []
    assert job.status == AppleJobStatus.running


async def test_claim_frees_a_slot_taken_by_a_timed_out_job(client, store, monkeypatch):
    monkeypatch.setattr(settings, "apple_max_vms", 1)
    monkeypatch.setattr(settings, "apple_job_timeout_seconds", 1)
    host = await register(client)
    stuck = await queue_job(store)
    await queue_job(store)
    assert (await claim(client, host["token"])).status_code == 200
    stuck.claimed_at = datetime.now(UTC) - timedelta(seconds=5)
    second = (await claim(client, host["token"])).json()
    assert stuck.status == AppleJobStatus.error and second["id"] != stuck.id


def test_tokens_are_not_logged(caplog, store):
    import asyncio

    caplog.set_level("DEBUG")
    _host, token = asyncio.run(apple.create_host(FakeSession(store), "m"))
    assert token not in caplog.text
