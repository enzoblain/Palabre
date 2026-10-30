# DevOps audit: CI, deployment, release, updater, toolchains

Scope: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `.github/scripts/compose-smoke.sh`,
`.github/dependabot.yml`, `docker-compose.yml`, `backend/Dockerfile`, `backend/docker-entrypoint.sh`,
`frontend/Dockerfile`, `backend/app/toolchains.py` and the `install_toolchain` tool.

Audit only: no fix is made in this PR. Findings are sorted by severity (High, Medium, Low), then by
impact inside each level. Effort: S (under half a day), M (a day or two), L (more).
Line numbers are those of `dev` at the time of the audit. Where a cause is a hypothesis and not
something I reproduced, the finding says so.

## What already works well

- Every GitHub Action is pinned by SHA and Dependabot keeps the pins fresh.
- Backend dependencies are hash-locked (`--require-hashes`) and audited by `pip-audit`.
- Secrets are Docker secrets (files), and the compose smoke test checks they leak nowhere.
- `docker-entrypoint.sh` is idempotent and does not follow symlinks planted by agents.
- The fail-fast job proves the backend refuses to start on an empty secret.

## Summary

| # | Severity | Finding | Effort |
|---|----------|---------|--------|
| 1 | High | `install_toolchain` can fail with no useful message | S |
| 2 | High | GHCR package visibility is not guaranteed or checked | S |
| 3 | High | CI is slow and does duplicate work (release waits on it) | M |
| 4 | High | Desktop (Tauri) build is only exercised at release time | M |
| 5 | High | Updater has no rollback and follows `latest` blindly | M |
| 6 | Medium | `publish_version` timing against the CI of `main` | S |
| 7 | Medium | Claude Code install is unpinned and cached by Docker | S |
| 8 | Medium | Floating base images, no Docker/npm/cargo dependency watch | S |
| 9 | Medium | Release workflow has no gate, no timeouts, no `fail-fast: false` on images | S |
| 10 | Medium | Skip logic can hide a broken CI | S |
| 11 | Medium | Toolchain extraction and linking are not atomic | M |
| 12 | Medium | Ports published on all interfaces, plain HTTP | S |
| 13 | Low | Smoke test gaps (web image, hardcoded owner, downgrade step) | M |
| 14 | Low | Backend deps installed twice, backend image built four times in CI | S |
| 15 | Low | Toolchain housekeeping (old versions, global switch, no retry) | M |
| 16 | Low | Image names hardcoded to `enzoblain` | S |

## High

### 1. `install_toolchain` can fail with no useful message

- Where: `backend/app/toolchains.py:59-74` (only `httpx.HTTPError` is converted), `:147-179`
  (`_install_python`), `:263-265` (`_extract`); tool in `backend/app/mcp_server/tools.py:502-516`.
- What is wrong: the python install was reported to fail with no error message. Only
  `WorkflowError` carries a readable message to the agent. Everything else that can go wrong
  escapes as a raw exception: `OSError`/`PermissionError` from `shutil.rmtree`, `_make_private`,
  `bin_dir().mkdir`, `wrapper.write_text` or `_link` (the volume mixes uids and a setgid group, so
  permission errors are plausible), `tarfile.TarError`, `KeyError`/`ValueError` when the Node or Go
  JSON changes shape, `FileNotFoundError` from `(venv / "bin").iterdir()` when the venv is
  half-built. The MCP layer shows these as a generic tool error. I did not reproduce the python
  failure (no access to the production volume); this is the most likely cause, not a proven one.
  Also, `_run` (`:213-226`) runs pip with a stripped environment (`PATH=os.defpath`, `HOME=/nonexistent`,
  no proxy or CA variables), so on a host behind a proxy or a custom CA pip fails, and only the last
  1500 characters of output are returned.
- Severity: High. It blocks the team's setup and gives nobody a way to diagnose.
- Fix: wrap the body of `install()` in a catch for `OSError`, `tarfile.TarError`, `ValueError`,
  `KeyError`, convert to `WorkflowError(f"{name} install failed: {type(exc).__name__}: {exc}")`, and log
  the traceback server side. Pass through `HTTP(S)_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`,
  `PIP_INDEX_URL` to pip. Add tests that force each failure and assert the message.
- Effort: S.

### 2. GHCR package visibility is not guaranteed or checked

- Where: `.github/workflows/release.yml:14-48` (push), `docker-compose.yml:190,223,234-262` (pull by
  the user and by the updater), `.github/workflows/ci.yml:117-138` and
  `.github/scripts/compose-smoke.sh:55-57` (smoke pulls the published image).
- What is wrong: a package first pushed by a workflow is **private** by default. Then
  `docker compose pull` and the updater fail for any user who is not logged in to GHCR, with a
  "denied" message that the updater only logs (`Update failed: ...`, `:259`), so a self-hosted
  install silently never updates. The CI smoke test only works because it logs in with
  `GITHUB_TOKEN` and `packages: read`: it would not notice a private package. It also cannot run on
  fork PRs for the same reason. Visibility is a one-time manual setting nobody verifies.
- Severity: High: the whole distribution path depends on it.
- Fix: make both packages public once (package settings, and link them to the repository; the
  `org.opencontainers.image.source` label from `docker/metadata-action` helps). Add a last step to
  the `images` job that checks anonymous access (`curl` the anonymous token endpoint and then the
  manifest, or `docker manifest inspect` after `docker logout`) and fails loudly. Run the smoke
  test's pull step without login so it covers what users do. Document it in the README.
- Effort: S.

### 3. CI is slow and does duplicate work

- Where: `.github/workflows/ci.yml:11-17` (triggers), `:22-24` (concurrency), `:93-114` (docker),
  `:117-138` (compose), `:155-177` (failfast).
- What is wrong:
  - `push: ["**"]` and `pull_request` both trigger on a PR branch. The concurrency group is
    `ci-${{ github.ref }}`, and the refs differ (`refs/heads/x` vs `refs/pull/N/merge`), so the two
    runs never cancel each other: every PR commit costs two full runs, compose smoke included.
  - The backend image is built from scratch in four places per run: the `docker` job, `compose`
    (`dc build backend` twice in `compose-smoke.sh:~160,~190`, the second one cached locally only)
    and the two `failfast` cases. Only `docker` and `failfast` use the GHA cache, and `compose`
    uses none.
  - The `compose` job (25 min timeout) is by far the longest and runs after merge on `dev` and `main`
    as well, so the release waits for it.
  - Backend and compose jobs are independent, but nothing is shared between them.
- Severity: High: this is the delay the lead notices at every release.
- Fix:
  - Keep the PR trigger and restrict `push` to `dev`, `main` and tags, or keep `push` and drop
    `pull_request` (the file header explains why `push` was added; fall back to `push` only for
    non-PR branches by looking at whether an open PR exists, or use one concurrency group keyed on
    `github.head_ref || github.ref_name`).
  - Build the backend image once in a first job (`load` + `docker save` as an artifact, or push a
    `ci-<sha>` tag to GHCR), and make `compose` and `failfast` load it instead of rebuilding.
    Pass `cache-from type=gha,scope=palabre` to every build as a minimum.
  - Run the upgrade/updater part of the smoke test only on `main` and release PRs, and the fresh start
    everywhere else.
  - Record job durations for a week to pick the real critical path (I did not have the run history).
- Effort: M.

### 4. The desktop (Tauri) build is only exercised at release time

- Where: `.github/workflows/release.yml:90-132`; nothing in `ci.yml` touches `frontend/src-tauri`.
- What is wrong: a change to `src-tauri/`, `Cargo.toml`, `tauri.conf.json` or a frontend change that
  breaks the bundle is only found after the tag, on four runners (two macOS, Windows, Linux). A
  failed `desktop-app` leaves a public release without apps, and the images are already pushed.
  Node is 20 here and 22 in CI and in the Dockerfile; `dtolnay/rust-toolchain` follows `stable`, so
  the toolchain changes under us.
- Severity: High: it breaks the release path and nobody sees it before.
- Fix: add a CI job on Linux that runs `cargo check` (or `tauri build --no-bundle`) when `frontend/**`
  or `src-tauri/**` changes (path filter on a dedicated job, with `swatinem/rust-cache`). Align Node on
  22 and pin the Rust toolchain version in a `rust-toolchain.toml`.
- Effort: M.

### 5. Updater has no rollback and follows `latest` blindly

- Where: `docker-compose.yml:231-262`.
- What is wrong:
  - It pulls `latest` and recreates `backend` and `web`. If the new backend does not start or
    migrates the volume (`docker-entrypoint.sh` migration) and then crashes, nothing goes back to the
    previous image: the server stays down until a human acts. There is no plan B.
  - `docker.sock` is mounted in a container: root on the host if the container is compromised. The
    image is pulled from a registry we control, but the surface is worth stating.
  - Pulling failures are only printed (see 2); there is no alert. No health check is waited for after
    `up -d`, `web` has no healthcheck and `depends_on` has no condition.
  - A breaking minor in 0.x is applied automatically.
- Severity: High for people running it unattended on a NAS.
- Fix: before `up`, record the running image digests; after `up -d --wait`, if the backend is not
  healthy within N seconds, retag/restore the previous digests and `up -d` again, and log it loudly.
  Add a healthcheck to `web`. Offer `PALABRE_VERSION` as a `X.Y` tag to follow only patches. Document
  the `docker.sock` trade-off, or move the updater to a host-side cron/systemd timer.
- Effort: M.

## Medium

### 6. `publish_version` timing against the CI of `main`

- Where: `.github/workflows/ci.yml:11-17,117-120`; the gate is in `backend/app/github.py:~262`
  (`check-runs` of the head commit) and the README ("CI must be green on it").
- What is wrong: after `merge_release`, the merge to `main` starts a full CI run (compose smoke
  included, see 3). `publish_version` refuses while any check is pending, so the lead polls or is
  woken, and the tag is pushed several minutes after the merge. Two more problems: a re-run of a
  flaky job on `main` makes the head look not green again, and the check-runs list includes the push
  and pull_request runs and can paginate (default 30 per page), so a pending run may be missed.
- Severity: Medium: slow, not wrong.
- Fix: (a) quick win: on `main`, skip the jobs that already ran on the release PR for the same tree
  (the merge commit of a squash differs, so key on "tree SHA equal to the PR head's tree"), or run
  only the fast jobs; (b) move the "CI green" wait into the backend (wait with a deadline and then
  tag itself) so nobody polls; (c) use `per_page=100` and check `conclusion`, not only `status`.
  Longer term, tag from a `workflow_run` on CI success.
- Effort: S for (c) and the wait, M for (a).

### 7. Claude Code install is unpinned and cached by Docker

- Where: `backend/Dockerfile:330-332`, `docker-compose.yml:195`.
- What is wrong: `curl -fsSL https://claude.ai/install.sh | bash -s -- stable` runs at build time
  with no checksum. Two consequences: a build is not reproducible, and the layer text is identical
  from one build to the next, so BuildKit (and the GHA cache with `mode=max`) keep serving an old
  "stable" until the cache is evicted. Released images can therefore ship an old or an unexpected
  Claude Code version.
- Severity: Medium.
- Fix: pass an exact version (`CLAUDE_CODE_VERSION=x.y.z`) from the release workflow as a build arg,
  resolved when tagging and recorded in the image label; keep `stable` for local builds only. Verify
  the downloaded installer or binary against a published checksum if one exists.
- Effort: S.

### 8. Floating base images, no Docker/npm/cargo dependency watch

- Where: `backend/Dockerfile:1`, `frontend/Dockerfile:5,11`, `docker-compose.yml:174,234`,
  `.github/dependabot.yml`.
- What is wrong: `python:3.12-slim-bookworm`, `node:22-slim`, `nginx:1.27-alpine`,
  `postgres:16-alpine` and `docker:27-cli` are tags, not digests. Dependabot only watches
  `github-actions` and `pip`: the frontend (`package-lock.json`), `Cargo.lock`, and the Docker
  images are not watched, and there is no `npm audit` or `cargo audit` next to `pip-audit`.
  `postgres:16` also needs a plan for the day 16 is end of life. This is a dependency topic: to
  review with Inès.
- Severity: Medium.
- Fix: add the `docker`, `npm` and `cargo` ecosystems to Dependabot (weekly, target `dev`,
  grouped), add `npm audit --omit=dev --audit-level=high` to the frontend job and `cargo audit` to
  the Tauri job of 4. Pin base images by digest, let Dependabot bump them.
- Effort: S.

### 9. Release workflow has no gate, no timeouts, and the images job fails fast

- Where: `.github/workflows/release.yml:14-22` (no `fail-fast: false`, no `timeout-minutes`), `:90`,
  `:136-138`.
- What is wrong: a tag pushed by hand (README describes it) builds and publishes `latest` with no check that CI
  passed on that commit or that the version files match (`publish_version` checks, the workflow
  does not). If the `palabre` build fails, the `palabre-web` one is cancelled, and a re-run rebuilds
  both. No job has a timeout, so a stuck macOS runner holds the release for 6 hours. `latest` is
  pushed for every tag, including a pre-release such as `v1.0.0-rc.1`. No SBOM, provenance or vulnerability scan on the published images.
- Severity: Medium.
- Fix: a first job that checks the tag is `vX.Y.Z` and equals the versions in the files, and that the
  commit has a green CI (`gh api .../check-runs`). Add `fail-fast: false` and `timeout-minutes` to every job,
  push `latest` only for non-prerelease tags, enable `provenance: true` and a Trivy/Grype scan (report only first).
- Effort: S.

### 10. Skip logic can hide a broken CI

- Where: `.github/workflows/ci.yml:43-47` (detect tests), `:68-75` (detect check script),
  `:57` and the `exit 5` handling (`:57-63` of the pytest step).
- What is wrong: the header says the skips exist "so the workflow is green before pytest exists".
  That was useful at bootstrap. Now, deleting `requirements-dev.txt`, renaming the `check` script or
  breaking test collection (exit code 5, "no tests collected") all turn the job green. A refactor
  that moves tests out of the collected path would pass CI.
- Severity: Medium.
- Fix: remove the detect steps and the exit-5 tolerance now that both suites exist; a missing file
  becomes a red job. Add a minimum count (`--co -q | tail -1`) if desired.
- Effort: S.

### 11. Toolchain extraction and linking are not atomic

- Where: `backend/app/toolchains.py:91-98` (Node), `:127-129` (Go), `:246-277`.
- What is wrong: the "already installed" test is `target/bin/node` (or `go/bin/go`) existing, but the
  archive is extracted straight into the final directory. If the backend is killed mid-extract (it has a
  60 s stop grace period and installs can last longer), the directory has `bin/node` but a partial
  `lib/`, and every later install says "installed". `_link` does `unlink` then `symlink_to`, so there is a
  moment where `node` does not exist for agents running right now. Python wrappers are rewritten the same way.
- Severity: Medium.
- Fix: extract into `<target>.partial` and `rename` when complete; create the symlink under a temp
  name and `os.replace` it. Write the wrapper scripts with a temp file and `os.replace`.
- Effort: M.

### 12. Ports published on all interfaces, plain HTTP

- Where: `docker-compose.yml:213-214,228-229`.
- What is wrong: the API (admin token in a bearer header) and the web app are published on
  `0.0.0.0` over HTTP. On a NAS or a VPS they are reachable from the whole network or the Internet,
  and the token travels in clear. `.env.example` and the README should say what to put in front.
- Severity: Medium. Mostly a doc gap but with a real risk; to share with Inès.
- Fix: default to `127.0.0.1:${PALABRE_PORT:-2710}:8000` with a documented override for LAN use, and
  document a reverse proxy with TLS (Caddy or Traefik snippet).
- Effort: S.

## Low

### 13. Smoke test gaps

- Where: `.github/scripts/compose-smoke.sh:~129-150,~165-175,~196`.
- What is wrong: the `web` image is built in CI but never started: nothing checks that nginx serves
  the app and proxies `/api` to the backend. The upgrade step ends by running the *old* image on the
  *new* volume ("downgrade"), which is more a curiosity than a requirement. The script hardcodes
  `ghcr.io/enzoblain/palabre:$OLD`. It writes a `.env` in the checkout and removes it on exit, so a crash
  mid-way (SIGKILL) leaves one behind that blocks the next run by design.
- Severity: Low.
- Fix: start `web` in the fresh-start phase and assert `GET /` and `GET /api/catalog/modes` through it;
  derive the image name from `GITHUB_REPOSITORY`; use `docker compose --env-file "$tmp/.env"` instead of
  writing in the repository.
- Effort: M.

### 14. Redundant work inside jobs

- Where: `.github/workflows/ci.yml:49-54` (two `pip install` of the same file), `:99-110` (`pip-audit` job
  reinstalls Python and itself).
- What is wrong: `requirements.txt` is installed, then installed again with the dev lock. `pip-audit` is a
  separate job that could be a step of the backend job (it uses the same Python, and pip cache) or run
  on a schedule rather than at every push, where a new CVE would make an unrelated PR red.
- Severity: Low.
- Fix: install once; run `pip-audit` on PRs touching `backend/requirements*` and on a daily schedule.
- Effort: S.

### 15. Toolchain housekeeping

- Where: `backend/app/toolchains.py:59-74,232-243,268-277`.
- What is wrong: old Node/Go versions stay in `/data/toolchains` forever (about 200 MB each); installing
  another version switches the whole team immediately, even for a run in progress; the downloads have no
  retry (one flaky network call fails the install, only a `WorkflowError` message to the agent);
  `https://go.dev/dl/?mode=json&include=all` and `index.json` are downloaded in full on every call;
  `pip install` from PyPI with no hash requirement is by design the agent's request but is a supply
  chain entry point (version pins are allowed but not required): to review with Inès.
- Severity: Low.
- Fix: keep the two latest versions and delete the others after a successful switch; retry
  idempotent GETs three times with backoff; cache the release index for a few minutes; recommend
  `==` pins in the tool description.
- Effort: M.

### 16. Image names hardcoded to the owner

- Where: `docker-compose.yml:190,223`, `.github/workflows/ci.yml:177`, `.github/scripts/compose-smoke.sh`
  (the `ghcr.io/enzoblain/palabre:$OLD` references), README.
- What is wrong: a fork cannot use the compose file or the smoke test without editing four places.
  `release.yml` uses `github.repository_owner`, so images go to the fork's namespace while compose points to
  `enzoblain`.
- Severity: Low.
- Fix: `${PALABRE_IMAGE_OWNER:-enzoblain}` in the compose file, and `${GITHUB_REPOSITORY_OWNER}` in CI.
- Effort: S.

## Suggested order

1. S items that unblock people: 1, 2, 10, 6 (the wait/pagination part).
2. 3 and 4 together (they touch `ci.yml`), then 5.
3. 7, 8, 9, 12 as one "supply chain and hardening" PR, reviewed by security.
4. The rest as time permits.
