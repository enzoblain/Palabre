# Tests

Backend tests (pytest, no database or network needed):

```sh
cd backend && pip install --require-hashes -r requirements-dev.txt && python -m pytest
```

On GitHub Actions, a hook in `tests/conftest.py` prints an `::error` annotation (file, line, test name) for each failed test, so the names show on the PR. GitHub keeps only 10 error annotations per step; the full list is in the log (`-rfE`). The frontend check has no such annotation.

Frontend: `cd frontend && npm run check` runs the typecheck, the build, the component tests (Vitest with jsdom and Testing Library, `src/**/*.test.tsx`), the pure-helper tests (Node's test runner, `scripts/*.test.mjs`), then the i18n and CSP checks.

Mac builder worker (stdlib, no Mac needed): `cd deploy/apple-host && python3 -m unittest test_worker`, see [Mac builder](apple-host.md).

Compose smoke test (needs docker, takes a few minutes):

```sh
.github/scripts/compose-smoke.sh
```

It brings up the real `docker-compose.yml` with throwaway secrets (it writes its own `.env`, removed on exit, and refuses to run over yours or a compose override) and checks that: the API answers 401 without or with a wrong token and 200 with the right one; no secret appears in the backend's `env`, `/proc/1/environ` or `docker inspect`; the `agent` user exists and can read neither `/run/secrets` nor `/run/palabre-secrets`; the version under test starts on a volume used by the last published version (data kept, volume migrated); the agent pool is isolated on the real container (`check-isolation.sh` with `CHECK_POOL_ONLY=1`: two simultaneous runs cannot read each other's `/proc/<pid>/environ` or MCP config, `sudo -l` shows exactly the nine rules (the pool users, plus root for the four `palabre-claim-clone` ones), a `setsid` process left by a run is gone when the account is leased again); and the `updater` recreates the backend with the secrets still resolved. Without a published version (or one older than Docker secrets), the upgrade and updater steps are skipped with a notice. In CI this is the `Compose smoke test` job, run on pull requests and on pushes to `dev` and `main`; failures show as `::error` annotations.

`tests/conftest.py` holds the shared fixtures: `FakeSession` (in-memory stand-in for
`AsyncSession`), object builders (`make_task`, `make_employee`...), `process` (sets the mode's
merge gates) and `fake_github` (replaces the GitHub and git calls). Counting queries can run against an in-memory SQLite session (`aiosqlite`, dev only), see `tests/test_context_reset.py`.
