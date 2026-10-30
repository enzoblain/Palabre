# Audit: tests and QA process

Scope: test coverage, the CI, and the QA/review process. Findings are sorted by severity (high, medium, low). Effort: S (under a day), M (a few days), L (a week or more). No fix is part of this audit.

Method: read `backend/tests/`, `backend/app/`, `.github/workflows/ci.yml`, `frontend/package.json`, `workflow.merge_blockers`, and the QA runs reported by the team. The desk of this audit has no `pytest`, so the suite was not run there (see Q1).

## High

### Q1. QA desks cannot run the tests or the app
- Problem: the QA desk has no `pytest`, no `gh`, and one run hit a corrupted git object (`git fsck` still reports dangling commits in a desk). QA then reduces to reading the diff, which is not QA.
- Where: desk provisioning (`worktrees.py`, `toolchains.py`), the QA position's tools.
- Severity: high. The QA gate (`qa_gate` in `workflow.py`) certifies something that was not executed.
- Fix: provision the Python venv with the dev requirements (`requirements-dev.txt`) on every QA desk before the first wake-up; recreate the desk from a fresh clone when `git fsck` fails; give QA a read-only way to get CI status (the backend already has `github.checks_status`, expose it as an MCP tool) instead of `gh`. Have QA state in the report whether tests were run or only the diff read.
- Effort: M.

### Q2. A QA "comment" verdict silently blocks the merge
- Problem: `merge_blockers` ignores `comment` reviews (`workflow.py`, `latest` skips `Verdict.comment`), and the gate needs a QA `approve`. A QA who writes a passing report with `comment` leaves "QA has not approved" and the PR stalls; nothing tells QA why.
- Where: `workflow.py` (`merge_blockers`), `mcp_server/tools.py` (`review_task`), the QA prompt in `orchestrator/prompts.py`.
- Severity: high (stalled merges, manual unblocking by the lead).
- Fix: state in the QA prompt that only `approve` or `changes` count; make `review_task` warn when the caller's role is a required gate and the verdict is `comment` (the tool already returns what still blocks the merge, so add the explicit hint there); add a test for the QA-comment case.
- Effort: S.

### Q3. Approvals recorded under the CEO's name
- Problem: several approvals were posted as Enzo, who by design never writes in team channels. Approvals count toward `required_approvals` and the QA/security gates by role, so a CEO identity that carries the reviewer/qa/security roles can satisfy gates without any review.
- Where: `workflow.py` (`approvers`, role checks), `company/team.py` (role assignment), `mcp_server/permissions.py`.
- Severity: high (the "one approval and a QA pass" rule is bypassable and the audit trail is misleading).
- Fix: exclude the CEO (and the task's own assignee) from `approvers`; record who triggered each review and surface it in the PR comment; add tests for both exclusions.
- Effort: S.

### Q4. No frontend tests, and the front check is only a build
- Problem: `npm run check` is `tsc --noEmit` plus `vite build`. No test runner, no component, router or `api.ts` tests, no lint. The frontend job also silently skips when the script is missing.
- Where: `frontend/package.json`, `.github/workflows/ci.yml` (job `frontend`).
- Severity: high for a UI that holds the whole product surface.
- Fix: add Vitest and Testing Library; start with `api.ts`, `router.ts`, `util.ts`, then the main components; add ESLint to `check`; make the CI job fail instead of skip once the script exists in `dev`.
- Effort: L.

## Medium

### Q5. Several backend modules have no test at all
- Problem: no test file references these modules: `api/rooms.py`, `api/monitoring.py`, `orchestrator/retries.py`, `orchestrator/scheduler.py`. Barely covered (one test file mentions them): `api/conversations.py`, `api/deps.py`, `credits.py`, `hardening.py`, `orchestrator/credit_watch.py`, `accounts.py`, `toolchains.py`, `orchestrator/dispatcher.py`, `mcp_server/server.py`, `runner.py`, `mcp_server/tools.py`. This is a text search, not a coverage measurement.
- Where: `backend/app/` as listed.
- Severity: medium. The untested `retries.py` and `scheduler.py` drive agent wakeups and rituals, the most failure-prone part of the product.
- Fix: measure first (add `pytest-cov`, publish the report in CI); then cover retries, scheduler, dispatcher and the MCP tools (one test per tool and per role); set a floor on the coverage and raise it over time.
- Effort: L.

### Q6. Tests rely on fakes only, so DB and git behavior are never exercised
- Problem: `FakeSession` and `fake_github` (`tests/conftest.py`) replace the database and git. Queries (joins, `selectinload`, ordering) and real `git` commands (rebase, worktree, rename on submit) are never run, apart from one SQLite test. SQLite is not PostgreSQL.
- Where: `tests/conftest.py`, `workflow.py`, `worktrees.py`, `github.py`.
- Severity: medium.
- Fix: add a small integration layer: a PostgreSQL service in the CI job, and tests that run `worktrees.py` against a temporary local bare repository (no network).
- Effort: M.

### Q7. Tests depend on the runner's environment
- Problem: `conftest.py` sets `ADMIN_TOKEN` with `setdefault`, so a real value in the runner's environment changes the suite; `test_isolation_image.py` is skipped when `sh` is missing and `test_resubmit_title.py` uses hard-coded `/tmp` paths; behavior also differs under `GITHUB_ACTIONS`. A skip is reported as green.
- Where: `tests/conftest.py:19`, `tests/test_isolation_image.py:50`, `tests/test_resubmit_title.py`.
- Severity: medium (a green suite that differs per machine).
- Fix: force the test settings with `monkeypatch`/an autouse fixture that clears the relevant variables; use `tmp_path`; fail rather than skip in CI (`-W error`, or check the skip count).
- Effort: S.

### Q8. CI tolerates "no tests collected" and skipped jobs
- Problem: the backend job exits 0 on pytest code 5 and skips when `requirements-dev.txt` is absent; the frontend job skips without a `check` script. Pointless now that both exist; it hides an accidental deletion of the tests.
- Where: `.github/workflows/ci.yml` (jobs `backend`, `frontend`).
- Severity: medium.
- Fix: remove the detection steps and fail on code 5.
- Effort: S.

### Q9. No written QA checklist or report format
- Problem: nothing defines what QA must verify (acceptance criteria, edge cases, run the app) or how to report it. Reports vary and do not say what was actually run. Acceptance criteria are free text, not tied to a test.
- Where: QA prompt in `orchestrator/prompts.py`, README "Tests".
- Severity: medium.
- Fix: a short template (commands run and their result, criteria checked one by one, bugs filed) posted as the QA review body; ask developers to name the test that covers each criterion in the PR.
- Effort: S.

## Low

### Q10. Duplicate and overlapping test files
- Problem: `test_ci_annotation.py` and `test_ci_annotations.py` sit next to a `tests/ci_annotation.py` helper; `test_hardening.py` and `test_git_hardening.py` overlap in name and likely in scope.
- Where: `backend/tests/`.
- Severity: low.
- Fix: merge or rename by what is tested.
- Effort: S.

### Q11. Compose smoke test is slow and partly skipped
- Problem: the upgrade and updater steps are skipped without a published version, so the migration path is untested in that case. It only runs on PRs and on `dev`/`main`.
- Where: README "Tests", `compose` job in `ci.yml`.
- Severity: low.
- Fix: report skipped steps as a CI warning annotation; keep a fixture volume of an old schema for the migration check.
- Effort: M.

### Q12. No regression rule for bug tickets
- Problem: bugs filed by QA are fixed without a requirement to add a failing test first.
- Where: process (bug tickets, `report_bug`).
- Severity: low.
- Fix: add "a test that fails before the fix" to the acceptance criteria that the lead copies from a bug ticket.
- Effort: S.
