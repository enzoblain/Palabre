# Audit: tests and QA process

Findings only, no fix applied. Each item gives the problem, where, severity, proposed fix and effort (S < 1 day, M 1-3 days, L > 3 days). Sorted by severity. Line numbers refer to `dev` at the time of writing.

Baseline: about 347 backend test functions in 33 files, all run without database or network; no frontend tests; CI runs pytest, `npm run check`, two Docker builds, the compose smoke test and pip-audit.

## Critical

### Q1. The schema is never tested against a real PostgreSQL

- Problem: all business logic is tested against `FakeSession`, which ignores the query. SQL filters, joins, `selectinload`, constraints, and the home-made migration (`create_all` plus `ALTER TABLE ... ADD COLUMN`) never run in CI. A wrong filter (e.g. the reviews of the current round) or a broken column migration only shows up in production. The only real-SQL strategy is an SQLite session used by one file.
- Where: `backend/tests/conftest.py:1-37` (docstring and `FakeSession`), `backend/app/db.py:26-34` (migration by ALTER), `backend/tests/test_context_reset.py` (the only SQLite use). `tests/test_merge_blockers.py` cannot check `Review.round == task.review_round` (`app/workflow.py:495-499`).
- Severity: critical
- Fix: add a small integration layer on a real database (a `postgres` service in the CI backend job, or testcontainers locally), with a `db` fixture that creates the schema in a transaction. Cover the queries of `workflow.merge_blockers`, `list_tasks`, `clean_up_finished_tasks`, the dispatcher's wakeup selection, and a migration test (old schema, then `init_db`). Keep `FakeSession` for pure logic.
- Effort: L

### Q2. The run loop of the orchestrator is almost untested

- Problem: `Dispatcher` (438 lines: `_dispatch`, `_run`, `_prepare`, `_finish`, `_requeue`, `_check_task`, `_check_rate`) is only touched indirectly by two files (`test_rate_limit.py`, `test_context_reset.py`). `scheduler.py` (rituals, daily jobs, idle conversations) and `retries.py` (failed task retries, backoff) have no test at all. These modules decide when agents run, are retried or are dropped; a regression stalls the whole company silently.
- Where: `backend/app/orchestrator/dispatcher.py:102-438`, `backend/app/orchestrator/scheduler.py:31-120`, `backend/app/orchestrator/retries.py:21-90`, `backend/app/orchestrator/research.py`.
- Severity: critical
- Fix: tests that drive `_dispatch` with a fake runner (parallelism limit, one run per employee, requeue on usage limit, task precondition checks, failure recording) and tests for the scheduler/retries with a frozen clock. Needs Q1's DB fixture for the wakeup queries.
- Effort: L

## High

### Q3. No coverage measure, no coverage gate

- Problem: nobody can tell which lines are tested; the figures above come from grep. `pytest-cov` is not in `requirements-dev.in`, and CI has no threshold or report. Untested modules (Q2, Q4) go unnoticed in review.
- Where: `backend/requirements-dev.in`, `.github/workflows/ci.yml` (job `backend`, step `pytest`).
- Severity: high
- Fix: add `pytest-cov`, print the report in CI (`--cov=app --cov-report=term-missing`), then enforce a floor (`--cov-fail-under`) set just under the current value and raised over time. Optionally per-module floors for `workflow`, `dispatcher`, `release`, `worktrees`.
- Effort: S

### Q4. The task lifecycle in `workflow.py` is tested only at its edges

- Problem: `merge_blockers` is well covered (`test_merge_blockers.py`), but `create_task`, `start_task`, `review_task`, `report_bug` and the whole `submit_for_review` (PR creation, resubmit, round counting) are touched by one or two files each, with no happy path plus error paths per function. `merge_task` has the dependency wake-up loop (`app/workflow.py:569-606`), where a task is unblocked only if all its dependencies are done: no test of a partial dependency set.
- Where: `backend/app/workflow.py:174-406` (creation to submission), `:439-475` (`review_task`), `:569-606` (`merge_task`).
- Severity: high
- Fix: one test module per function group (`test_task_lifecycle.py`) using `FakeSession` for the logic, plus Q1's DB fixture for state transitions (`todo` to `in_progress` to `review` to `changes_requested` to `done`), review rounds, self-review refusal, and unblocking.
- Effort: M

### Q5. The frontend has no tests, and its only check is the build

- Problem: `npm run check` is `build`, i.e. `tsc --noEmit` plus `vite build`. No unit, component or API-contract test, no linter, no formatter check. A change of a backend response shape breaks the UI without any failing test. The Tauri shell (`src-tauri`) is not built in CI at all.
- Where: `frontend/package.json:6-12`, `frontend/src/api.ts`, `.github/workflows/ci.yml` (job `frontend`).
- Severity: high
- Fix: add Vitest and Testing Library for `api.ts`, `router.ts` and the main components; add ESLint to `check`. For the contract, generate the TypeScript types from the FastAPI OpenAPI schema, or add a backend test that snapshots `app.openapi()`. Build the Tauri shell on release only.
- Effort: M

### Q6. CI skips silently instead of failing

- Problem: the backend job tolerates pytest exit code 5 ("no tests collected") and skips tests when `requirements-dev.txt` is missing; the frontend job skips when there is no `check` script. Those guards were meant for the bootstrap of the repository; today a broken path, a bad `testpaths` or a deleted script yields a green check with nothing run. Branch protection counts that as success.
- Where: `.github/workflows/ci.yml:45-70` (detect steps and the `code -eq 5` branch), `:83-98` (frontend detect).
- Severity: high
- Fix: remove the detection steps and the exit-5 tolerance now that both exist; let the jobs fail when something is missing.
- Effort: S

### Q7. A QA or reviewer comment does not approve, and nothing tells the author what is missing

- Problem: with `qa_gate` on, the merge needs a QA `approve`. A verdict of `comment` is ignored by `merge_blockers` (`app/workflow.py:500-505`), so a QA that writes a review as a comment ("looks good", "tested, OK") leaves the PR blocked with "QA has not approved" and nobody woken up: the verdict is recorded, `wake_lead` fires, but nothing asks QA to conclude. Tasks sit in `review` until the lead notices.
- Where: `backend/app/workflow.py:439-475` (`review_task`), `:491-516` (`merge_blockers`), `backend/app/mcp_server/tools.py` (review tool), `backend/app/orchestrator/prompts.py`.
- Severity: high
- Fix: (1) in the QA/reviewer prompts, state that a conclusion must be `approve` or `changes`, and `comment` is for intermediate notes; (2) when a review is a `comment` from an employee whose approval is still required, return that blocker in the tool answer and re-wake them after N minutes (as `merge_retry_at` already does for CI); (3) show pending approvers in the room document.
- Effort: M

### Q8. Every rebase restarts a full review/QA cycle

- Problem: `submit_for_review` increments the review round, and `merge_blockers` only reads reviews of the current round (`Review.round == task.review_round`, `app/workflow.py:495-499`). So a dev who only rebases on `dev` (asked for by the watcher when the PR conflicts, `merge_watch.py:103`) wipes the approvals: the reviewer, QA and security must all approve again, each costing a wakeup and a Claude run, and the PR can chase a moving `dev` indefinitely. The cap of "3 review rounds" (`skipped: 3 review rounds`, see `tests/test_rate_limit.py:52`) can be hit just by rebases.
- Where: `backend/app/workflow.py:344-406` (`submit_for_review`), `:495-505`, `backend/app/orchestrator/merge_watch.py:34-110`, `backend/app/worktrees.py:119` and `:245` (push with lease).
- Severity: high
- Fix: on resubmission, compare the diff against the base (`git range-diff` or `git patch-id` of the task's commits) with the previous submission; if only the base moved, keep the round and the approvals, and carry the verdicts over. Alternative: let the backend rebase clean conflicts itself. Test both paths (same patch-id keeps approvals, changed patch resets them).
- Effort: M

## Medium

### Q9. `worktrees.py` and `github.py` are tested through mocks of `git`

- Problem: `test_task_clones.py` replaces `git` (`:35-43`) and the GitHub calls are all faked, so the real git behaviour (clone, detach, push with lease, pull of `origin/*`, commit of a release on the team's branch) is checked only by the compose smoke test, which does not cover it. `github.py` (480 lines: PR creation, checks status parsing, merge, post_review) has no test of its response parsing against recorded payloads.
- Where: `backend/app/worktrees.py:60-327`, `backend/app/github.py`, `backend/tests/test_task_clones.py`.
- Severity: medium
- Fix: use real git against local bare repositories in `tmp_path` (fast, no network; only `asyncio.create_subprocess_exec` is blocked by the autouse fixture and would need an opt-out marker). For GitHub, use `httpx.MockTransport` with saved JSON payloads (checks, statuses, merge conflict, 422 on PR creation).
- Effort: M

### Q10. Release logic: pure functions tested, the publishing path less so

- Problem: `release.py` (pure) is well covered, but `projects.prepare_release` / `merge_release` and the main-branch CI wakeup depend on `worktrees.commit_release` and the tag/version detection, tested only with fakes (`test_release_auto.py`, `test_release_shipping.py`, which import each other's helpers). A wrong tag lookup or a push refused after a race is not exercised.
- Where: `backend/app/projects.py` (`prepare_release`, `merge_release`), `backend/app/worktrees.py:119-135`, `backend/tests/test_release_auto.py:9-15`.
- Severity: medium
- Fix: end-to-end release test on a temporary git repository with tags (no tag, one tag, `!` commit, a moved branch → push refused); move shared helpers to `conftest.py`.
- Effort: M

### Q11. Test fixtures are duplicated and cross-imported between test files

- Problem: `FakeSession` is defined in `conftest.py` but test files redefine their own (`WatchSession`, `FakeSession` in `test_release_shipping.py`) and import from each other (`from .test_merge_watch import ...`, `from .test_release_shipping import FakeSession`). Renaming a helper in one test breaks another module; each fake session answers queries in a different, order-dependent way (results queued in the order the code calls `scalars()`), so refactoring a query's order breaks tests that are logically unchanged. `test_rate_limit.py` hand-builds employees with `# fmt: skip`.
- Where: `backend/tests/conftest.py:27-36`, `backend/tests/test_release_auto.py:13-15`, `backend/tests/test_release_shipping.py`, `backend/tests/test_merge_watch.py`, `backend/tests/test_rate_limit.py:25`.
- Severity: medium
- Fix: one session fake in `conftest.py` (ideally matching on the entity of the query rather than the order), shared builders (`make_employee`, `make_run`, `make_wakeup`), no imports between test modules. Best done together with Q1.
- Effort: M

### Q12. No linter, formatter or type check on the backend

- Problem: `# fmt: skip` comments show a formatter is expected, but nothing runs one in CI; no `ruff`, `mypy` or `pyright` step, no pre-commit. Style and typing are left to reviewers.
- Where: `.github/workflows/ci.yml` (job `backend`), `backend/requirements-dev.in`, `backend/tests/*.py` (`# fmt: skip`).
- Severity: medium
- Fix: add `ruff check` and `ruff format --check` to the backend job (config in `pyproject.toml`), then a gradual `mypy`/`pyright` on `app/`.
- Effort: S (ruff), M (types)

### Q13. The compose smoke test is the only Docker-dependent check, and it is slow and all-or-nothing

- Problem: it needs Docker and published images, takes up to 25 minutes (`timeout-minutes: 25`), runs on every PR, and skips its upgrade/updater steps with a notice when no published version exists, so these can be green while untested. Nobody can run it without Docker, and `test_isolation_image.py` only greps `docker-compose.yml` and the entrypoint as text, so it does not check behaviour. Fork PRs cannot run it (package access).
- Where: `.github/scripts/compose-smoke.sh`, `.github/workflows/ci.yml:117-135`, `backend/tests/test_isolation_image.py:12,38,68`.
- Severity: medium
- Fix: split the script into independent jobs (secrets/isolation vs upgrade vs updater) so one failure points at one area; make skipped steps visible (a `::warning` and a job summary); keep it required only when `docker-compose.yml`, the backend `Dockerfile` or `docker-entrypoint.sh` change (path filter), and run it nightly otherwise.
- Effort: M

### Q14. Dependency of a PR's CI status on the push run vs the pull_request run

- Problem: CI runs on every push and on pull_request, so each commit pushed to a PR branch runs the whole pipeline twice (concurrency groups differ by `github.ref`, so they do not cancel each other). The Docker builds and pip-audit are repeated too. The README's note on annotations also says GitHub keeps only 10 annotations per step, so a large failure hides failing tests.
- Where: `.github/workflows/ci.yml:14-24` (`on`, `concurrency`), `README.md` (Tests section).
- Severity: medium
- Fix: keep the push trigger (it exists for good reason) but skip the heavy jobs (`docker`, `compose`, `pip-audit`) on pushes of branches that have an open PR, or give both events the same concurrency group keyed on the head SHA. Upload a JUnit XML artifact for the full failure list.
- Effort: S

## Low

### Q15. Two near-identical test modules for CI annotations

- Problem: `test_ci_annotation.py` and `test_ci_annotations.py` both exist, and the helper `tests/ci_annotation.py` sits in the test folder while being imported by `conftest.py` by absolute name (`from tests.ci_annotation import ...`), which only works with the current `pythonpath`.
- Where: `backend/tests/test_ci_annotation.py`, `backend/tests/test_ci_annotations.py`, `backend/tests/ci_annotation.py`, `backend/tests/conftest.py:133-146`.
- Severity: low
- Fix: merge the two modules, import the helper relatively.
- Effort: S

### Q16. Tests rely on real time and sleeps

- Problem: `asyncio.sleep(0.05)` and a 0.05 s agent timeout make the tests depend on the machine speed; they can flake on a loaded CI runner.
- Where: `backend/tests/test_claude_usage.py:97`, `backend/tests/test_agent_isolation.py:118,132`.
- Severity: low
- Fix: use `asyncio.Event` to synchronise, and a fake clock for the timeout.
- Effort: S

### Q17. The README promises a database-free suite but the dev requirements include aiosqlite

- Problem: the README says "no database or network needed" and `conftest.py` says "no SQLite driver", while `requirements-dev.in:5` adds `aiosqlite` and `test_context_reset.py` uses it. The documented strategy is stale, and the rule "discuss first" for real SQL has no owner. Also, SQLite differs from PostgreSQL (types, `ALTER`, locking), so these tests prove less than they seem to.
- Where: `README.md` (Tests section), `backend/tests/conftest.py:3-7`, `backend/requirements-dev.in:5`, `backend/tests/test_context_reset.py`.
- Severity: low
- Fix: update the docs when Q1 lands; move the SQLite-based test to the Postgres fixture.
- Effort: S

### Q18. The QA process is not documented as a checklist

- Problem: the README says a QA "reads the diff and approves or requests changes", but there is no definition of what QA checks (run the tests, try the endpoint, check migrations/backward compatibility, docs updated), nor of the expected evidence in the review body. Quality varies between runs, and the company sizes below `multinational` do not require docs updates.
- Where: `README.md` (How it works), `backend/app/orchestrator/prompts.py`, `backend/app/company/catalog.toml` (`qa_gate`, `docs_required`).
- Severity: low
- Fix: write a QA checklist in `docs/` and inject it in the QA prompt; require a short "tested: commands and result" section in a QA verdict.
- Effort: S
