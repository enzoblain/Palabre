# Apple mode

Apple mode lets the team build iPhone apps in Swift. The agents stay on our Linux servers; a dedicated
Apple-silicon Mac only **compiles and tests** inside throw-away macOS virtual machines (VMs). This page
fixes the structure; only the Mac builder registration and the job queue ([Implemented API](#implemented-api)) exist so far (see [Task breakdown](#task-breakdown)).
The screens (project type choice, Mac state, build result) are specified in [Apple mode UI](apple-mode-ui.md).

Rules set by the boss (decision 80), each one is enforced by a mechanism below:

| Rule | Mechanism |
|---|---|
| Agents stay on the Linux servers, the Mac only builds and tests | The Mac runs a small *host worker* that executes jobs; no `claude`, no orchestrator on it |
| A fresh macOS VM per attempt, destroyed afterwards, 2 VMs at most | Clone of a pinned image per job, deleted at the end; queue in the backend |
| No key on the Mac (Claude, GitHub, Apple) | Source is handed over by the backend, results are pushed back, signing happens in GitHub CI only |
| Mac isolated from the rest of the network | Outbound filtering of the VM, no shared folder, see [Network isolation](#network-isolation) |

## Overview

```
 Agent (claude -p, Linux)
   │ MCP: apple_build / apple_test
   ▼
 Backend ── apple_jobs table (queue) ◄──── host worker on the Mac (outbound HTTPS, polls)
   │                                           │ tart clone <pinned image> → run → delete
   │  source bundle (one-time URL)             ▼
   └──────────────────────────────────►  macOS VM (no secret, filtered network)
        ◄── logs, result, screenshots (job token, scoped to this job) ──┘

 Release: tag vX.Y.Z ─► GitHub Actions on a macOS runner ─► signing + upload (protected environment)
```

The Mac never receives a connection: the host worker calls the backend, so the Mac needs no open port
and the backend needs no route to the Mac's network.

## Declaring an Apple project

`Project` gets a `platform` column: `generic` (default, today's behavior) or `apple`. It is chosen at
creation (`POST /api/projects`, a "Swift / iPhone app" choice in the creation form and the mobile app)
and shown in Infos. It is stored separately from the existing `kind` because it says *what the code is*,
not how the company is organized. For an `apple` project:

- the agents' prompt gets a short Apple block (Swift, Xcode project layout, "build and test with
  `apple_build` / `apple_test`, never assume a local Xcode");
- the Apple tools below are offered to developers, QA and the reviewer (see `permissions.py`); on a
  `generic` project they answer "not an Apple project";
- the project must contain a `.palabre/apple.toml` (scheme, destination, Xcode version, optional
  `test_plan`), read by the backend from the task branch. **Its values are untrusted** (any agent or
  dependency PR controls the file): the backend validates `scheme`, `destination` and `test_plan` against a
  strict pattern (letters, digits, `.`, `_`, `-`, space, and for `destination` the `key=value,...` form)
  before queuing, and rejects the job otherwise. The Xcode version is only a *key*: the image is chosen by
  the server (see below), never by the file. Without the file the tools answer with the expected
  file, so an agent can add it itself;
- the apple mode must be enabled on the server (`APPLE_MODE_ENABLED`) and a host worker enrolled; otherwise
  project creation with `platform=apple` is refused with a clear error.

## Running a build or a test

Agents never talk to the Mac. They use MCP tools (listed in the catalog and `permissions.py`):

| Tool | Who | What |
|---|---|---|
| `apple_build` | dev, QA | Queues a build of the task's branch (current head); returns a job id |
| `apple_test` | dev, QA | Same, then runs the tests (`xcodebuild test`, optional `test_plan`, optional screenshots) |
| `apple_job` | dev, QA, reviewer | Status (`queued` with its position, `running`, `passed`, `failed`, `error`), summary and failed tests |
| `apple_job_logs` | dev, QA, reviewer | A page of the log (the tail by default), so a run never loads a huge log |
| `apple_cancel` | dev, QA | Planned, not in the first backend: cancels a queued or running job of the caller's own task (it will add a `cancelled` status) |

Jobs are asynchronous: an agent run is not kept waiting for a queue slot. The tool returns at once; when
the job ends, the backend posts a short system message in the task room and wakes the agent that queued
it (a new event type next to the CI events in `orchestrator/events.py`). A job is tied to the task and
to the head SHA it built, so a verdict on an old commit is never shown as current.

A result holds: the status, the duration, build errors and warnings parsed from `xcodebuild`, the failed
tests (name, message, file:line from the `.xcresult`), the log, and optional simulator screenshots. The
backend stores them in the database (summary) and in `APPLE_ARTIFACTS_DIR` (log, screenshots, kept
`APPLE_ARTIFACT_RETENTION_DAYS`). Build logs and failure messages are attacker-controlled text: the front and mobile apps render them as
plain text, and `apple_job_logs` stays paginated and capped. Screenshots are served by the API so the front and the mobile app can
show them; agents get their URL, never a path.

## Backend ↔ Mac

### Protocol

Pull model over HTTPS, using endpoints under `/api/apple-host/` (separate from the agents' MCP server and
from the apps' API, with their own auth):

1. `POST /api/apple-host/claim`: the host worker long-polls (about 25 s) and receives at most one job if
   fewer than `APPLE_MAX_VMS` VMs run. The job holds the commit, the validated `apple.toml` values, the
   image reference chosen by the server and a **job token**.
2. The worker clones the pinned image, starts the VM, then runs the job runner script in it with
   `tart exec`, passing the backend URL and the job token as an environment variable of that one process
   (Tart has no guest metadata channel). The worker then waits for it.
3. The VM downloads the source, builds, and uploads the logs and results with the job token. The build
   itself (`xcodebuild`) runs as a separate unprivileged guest user that cannot read the runner's
   environment, so build code (SwiftPM plugin, Run Script phase) never sees the token.
4. The worker sends `POST /api/apple-host/jobs/{id}/finish` (exit status) and runs `tart delete`. If the
   VM exceeds `APPLE_JOB_TIMEOUT_SECONDS`, the worker kills and deletes it, and the job ends as `error` with a summary saying the time limit was reached.
5. The worker sends a heartbeat every 15 s. A job whose worker went silent for `APPLE_HEARTBEAT_TIMEOUT_SECONDS`
   is marked `error`, its job token is revoked at that moment (the VM may still be running until the worker
   restarts) and its slot freed. The same revocation applies when the backend ends a job on the time limit. (The VM is deleted at the worker's next start, which wipes every
   VM that is not in its list of live jobs).

### Authentication, with no long-term secret on the VM

Two different credentials, with a different scope each:

- **Host worker credential** (on the Mac host, never in a VM): a random bearer token, sent in the
  `Authorization` header over HTTPS. Enrolled hosts live in an `apple_hosts` table (name, hashed token,
  created, expiry, last seen, revoked); only the hash is stored: the SHA-256 (hex) of the random token, looked up by its hash, never the token itself, so nothing depends on the reverse proxy (no client certificate, no header
  to forward or clean). It can only call `/api/apple-host/*`: claim a job, send heartbeats, finish a job.
  It cannot read a conversation or call GitHub, but it can read the source of the jobs it claims, which is
  why enrollment is gated and the token is revocable from the server (the `apple_hosts` row is marked
  revoked, the next call is refused). It expires after 90 days. **Renewal** (`POST /api/apple-host/renew`)
  needs a still-valid, non-revoked token: it returns a new one and the old one stops working, so a stolen
  token cannot renew itself after revocation. It is the only long-lived credential involved, it is not one
  of the three forbidden kinds (Claude, GitHub, Apple).
- **Enrollment** is never open: it needs a one-time enrollment code generated by an authenticated user of
  the app (single use, short TTL, stored hashed). Exchanging the code creates the `apple_hosts` row and
  returns the first token, shown once. Without a valid code the enrollment endpoint answers
  nothing useful, even when `APPLE_MODE_ENABLED=true`.
- **Job token** (the only secret that enters the VM): random, created when the job is claimed, valid for
  that job only, stored hashed, revoked when the job ends or times out, and usable only for three
  things: download this job's source bundle, upload its logs and results, read its own status. Same
  principle as the host token: only the SHA-256 (hex) of the random token is stored.

The source never needs a GitHub token on the Mac: the backend, which already holds the token and a clone
of each project (`worktrees.py`), builds a `git bundle` of the task branch at the job's SHA and serves it
at the one-time URL guarded by the job token. The VM unpacks it into its own disk.

## Virtual machines

### Tool and image

- **Tart** (Apple Virtualization framework, Apple silicon, runs macOS guests, APFS copy-on-write
  clones). Anka is paid; Tart is open source and widely used
  in CI. Apple's license limits a Mac to 2 macOS VMs at once, which `APPLE_MAX_VMS=2` reflects.
- **Base image**: built by us with Packer from a Cirrus Labs macOS base image, with a given Xcode, its
  simulators, `xcbeautify`, Ruby/`bundler`, SwiftLint, and a *job runner script* (a shell
  script, no daemon) that does the steps of step 3 above. Nothing is autostarted in the image: the worker
  runs that script with `tart exec`, passing the values as arguments and the job token in the environment.
  The image contains no credential. It is **pinned by digest** (`APPLE_IMAGE`, `name@sha256:...`), never
  by tag. The image is chosen **only by the server** from config: `APPLE_IMAGE`, or an allow-list of
  digests keyed by Xcode version; a value outside the list is rejected. The worker never takes an image
  from the job content or from `apple.toml`. The worker also never interpolates `apple.toml` values into a
  command it runs on the host: they enter the VM only as data (arguments of the guest script). Updating Xcode means building a new image, testing it, then changing the digest (one commit, one
  config change, revertible).
- **Plan B for the VM tool: UTM** (decision #84; same Apple virtualization, with a command line). To keep the switch cheap, the host worker calls the VM tool in **one place only** (a small
  module with `clone`, `run`, `exec`, `delete`, `list`); the rest of the worker and the backend only know
  those operations, not Tart.
- **One clone per job**: `tart clone <digest> job-<id>`, `tart run`, `tart delete`. A VM is never
  reused or reset in place, so a project cannot leave anything for the next one.

### Network isolation

The risk (raised by Inès): SwiftPM plugins and Xcode "Run Script" phases run arbitrary code at build
time, and by default Tart's NAT lets a VM reach the host and the LAN. So:

- VMs run with Tart's **softnet** (`--net-softnet`), with `--net-softnet-block` on the private ranges
  (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `100.64.0.0/10`, loopback/multicast),
  which covers the host and the LAN. The backend is reached through its public (or tunnel) address, which
  is allowed explicitly by `--net-softnet-allow` when the server is on a private address. Because that
  option takes a CIDR, the `pf` anchor below narrows it to the backend IP on port 443 only, so no other
  port of that host (the database included) is reachable.
- A **second layer** on the host: a `pf` anchor (`deploy/apple-host/com.palabre.apple-vm.pf.conf`) loaded at boot that blocks
  the private ranges and the Mac's own addresses from the VM subnet, DNS to the gateway excepted. A softnet bug must not be
  enough to reach the LAN. The worker refuses to start if the anchor is not loaded, and `check-isolation.sh`, run inside a
  VM, proves it (install, check and rollback: [Mac builder](apple-host.md)).
- The VM only gets DNS from its gateway (the one destination the anchor lets through on the private ranges); IPv6 is dropped on the VM bridge.
- Outbound internet is allowed because SwiftPM, CocoaPods, Homebrew and Apple's downloads need it; it is
  limited by the rules above, not by a host allow-list that would break packages. To tighten it later,
  `APPLE_EGRESS_ALLOW` can list domains (resolved to a `pf` table by the worker).
- **No shared folder** and no mounted volume with the host (`--dir` is never used); the clone is made
  inside the VM from the bundle.
- The Mac itself sits on its own VLAN or at least a router rule: its own network access is limited to
  the backend and Apple/GitHub package hosts. The host worker user is a non-admin account.
- The test the network task must pass: from a running VM, the host, the router, a LAN address and the
  backend's database port are all unreachable; the job endpoint and a public package host are reachable.

### Queue

The queue is the `apple_jobs` table (`queued → running → passed|failed|error`), no
extra broker. A job is claimed with `SELECT ... FOR UPDATE SKIP LOCKED`, only if fewer than
`APPLE_MAX_VMS` jobs run. Order: first in, first out, with at most `APPLE_MAX_QUEUED_PER_PROJECT` waiting
jobs per project and a newer job on the same task replacing a still-queued one (an old SHA is useless).
A job that waits more than `APPLE_QUEUE_MAX_WAIT_SECONDS` ends as `error`. The queue length and the
wait time are shown in monitoring, so the boss can see when 2 VMs are not enough.

## CI, signing and publication

- **PR checks for a Swift project**: a workflow template (`.github/workflows/swift-ci.yml` in the project,
  added by the creation of an `apple` project; pushing a file under `.github/workflows/` needs the `workflow`
  scope on the GitHub token, so if the token lacks it, the file is left to the project's first task instead) runs `xcodebuild test` on a pinned macOS runner image. It
  triggers on `pull_request` (never `pull_request_target`), pins third-party actions by commit SHA, has
  no secret and `contents: read` only. The "CI must be green to merge" rule applies as for any
  project; the VM job gives the agents their fast loop, the CI is the check of record. (GitHub macOS
  minutes cost more than Linux ones; the workflow only runs on PRs, with concurrency cancelation.)
- **Signing and publication** happen only in GitHub Actions, on a version tag, in a protected environment
  limited to `v*` tags (the pattern of `mobile-release.yml` and
  [Mobile release](mobile-release.md)): certificate, provisioning profile and App Store Connect key live
  in that environment's secrets, never in the repository, a VM or the Mac. The workflow archives, signs
  and uploads to TestFlight. The simulator build used by the VMs needs no signing.
- The agents never see signing secrets. Releasing stays the lead's `merge_release` step.

## Implemented API

Behind `APPLE_MODE_ENABLED` (otherwise `404`). Tokens are random and stored as a SHA-256 only, never logged.

| Route | Auth | What |
|---|---|---|
| `POST /api/apple-enrollment-codes` | admin | Generates a one-time code (`penr_...`); `201` with `{code, expires_at, ttl_seconds}`, the code is shown once, only its SHA-256 is stored |
| `POST /api/apple-host/enroll` `{name, code}` | the code | Spends the code and registers the Mac; `201` with its `pmac_` token, shown once. An unknown, expired or spent code is `401`; more than `APPLE_ENROLL_MAX_ATTEMPTS` attempts per IP in the window is `429 apple_enrollment_rate_limited` with `Retry-After` |
| `GET /api/apple-hosts` | admin | Macs with `last_seen_at` and `connected` (seen within `APPLE_HEARTBEAT_TIMEOUT_SECONDS`) |
| `DELETE /api/apple-hosts/{id}` | admin | Revokes the token: the Mac's next call is `401` |
| `POST /api/apple-host/heartbeat` | host token | `204`, records the Mac as seen |
| `POST /api/apple-host/claim` | host token | Next job (`id`, `branch`, `commit_sha`, `job_token`, `source_url`) or `204` (no job, or `APPLE_MAX_VMS` running). Plain request, no long poll yet |
| `GET /api/apple-host/jobs/{id}/source` | job token | The branch as a git bundle, once; `403 apple_job_token_used` the second time |
| `POST /api/apple-host/jobs/{id}/result` `{status, log_excerpt}` | job token | `status` is `passed`, `failed` or `error` (infra); `204`. The token is then spent: a second call is `403 apple_job_token_used` |

An invalid, unknown or revoked token is `401`. Running jobs past `APPLE_JOB_TIMEOUT_SECONDS`, or whose Mac went
silent, are ended as `error` (summary says which) and their job token is revoked; this is checked on every claim.
The tables are `apple_hosts` and `apple_jobs`, created at startup like the others. Queuing a job from the agents'
tools (`apple_build` / `apple_test`), renewal and the cancel/wait limits of this page are not built yet.
Enrollment codes live in `apple_enrollment_codes` (hash, expiry, consumption date). They last
`APPLE_ENROLLMENT_CODE_TTL_SECONDS` (15 minutes by default) and are spent by one conditional update in the same
transaction as the Mac's registration, so of two simultaneous exchanges only one succeeds. Every exchange attempt counts
against the caller's IP, valid or not (in memory, reset by a restart).

### Creating an Apple project

`POST /api/projects` takes an optional `platform` (`generic` by default, so nothing changes without it, or `apple`);
`ProjectOut` returns it. With `platform=apple` the request is refused with `422` and the code `apple_host_required`
(message in French: no Mac builder is connected) when `APPLE_MODE_ENABLED` is off or no Mac builder has answered within
`APPLE_HEARTBEAT_TIMEOUT_SECONDS`. The refusal comes before anything is created. When the GitHub repository is
empty, its first commit holds the starter Swift package next to the README: `Package.swift`, one source and one
`XCTest` test that passes, and a `.gitignore` that covers `.build/`. The module is named after the project
(`apple_template.module_name`). A repository that already has commits is left as it is. The package holds no
key, token or signing setting: signing stays in GitHub CI.

Revoking a Mac also ends its running jobs as `error` (summary `Mac builder revoked`), so their job tokens stop
working at once. A job token and the source download are each spent by one atomic conditional update: of two
concurrent calls with the same token, only one wins and the other gets `403 apple_job_token_used`. Claims are
serialised with a Postgres advisory lock, so two Macs cannot exceed `APPLE_MAX_VMS`. The source is marked as downloaded
before the bundle is built: if that fails (the branch moved), the token is spent and the Mac reports `error`.
Overdue jobs are only swept on a claim, so a dead Mac's job stays `running` until the next claim.

## Build result on the task

Each submission of an `apple` project's PR (`submit_for_review`, a rebase included) queues one job for the PR head,
tied to the task (`apple_jobs.task_id`). A head already built is not queued again, unless its build ended as an
infra error. Projects of any other platform queue nothing and keep their API unchanged.

- `get_task` and `GET /api/tasks/{id}` (and `apple_build` in the task detail) show the newest build of an Apple
  project: `job_id`, `status`, `commit_sha`, `infra_error`, `summary`, `errors` and `finished_at`. `errors` holds the
  last lines of the log that look like errors (`error:`, `failed`, `fatal`; at most 20 lines of 300 characters),
  untrusted text to render as plain text. `infra_error` is true for the `error` status (timeout, lost or revoked
  Mac): it is not a failing test.
- **Merge gate**: `merge_task` and `merge_blockers` refuse the merge unless the build of the head about to be merged
  is `passed`. The blocker says whether there is no build yet, it is queued or running, it failed (fix and submit
  again) or it hit an infra error (retry). The boss's `force` skips it like the other rules.
- **Retry**: `POST /api/tasks/{id}/apple-build/retry` (and the lead's `retry_apple_build` tool) queues the same commit
  again, only when the newest build ended as an infra error; any other state is `409 apple_build_not_retryable`.

## Configuration

To add to `backend/app/config.py` and [Configuration](configuration.md) (all optional, off by default):

| Variable | Default | What it does |
|---|---|---|
| `APPLE_MODE_ENABLED` | `false` | Allows `platform=apple` projects and exposes `/api/apple-host/*` and the Apple tools |
| `APPLE_MAX_VMS` | `2` | VMs running at once (Apple's limit per Mac; never above 2) |
| `APPLE_IMAGE` | | Image to clone, pinned by digest; refused if it has no `@sha256:` (or a digest allow-list keyed by Xcode version) |
| `APPLE_JOB_TIMEOUT_SECONDS` | `1800` | Maximum duration of a job before the VM is killed |
| `APPLE_HEARTBEAT_TIMEOUT_SECONDS` | `60` | Silence of the host worker after which its jobs are in error |
| `APPLE_QUEUE_MAX_WAIT_SECONDS` | `1800` | Wait in the queue before a job ends in error |
| `APPLE_MAX_QUEUED_PER_PROJECT` | `3` | Waiting jobs a project may have |
| `APPLE_ARTIFACTS_DIR` | `/data/apple-artifacts` | Where logs and screenshots are stored |
| `APPLE_ARTIFACT_RETENTION_DAYS` | `14` | Age after which logs and screenshots are deleted |
| `APPLE_LOG_MAX_BYTES` | `20971520` | Size beyond which a log is cut (the tail is kept) |
| `APPLE_HOST_TOKEN_TTL_DAYS` | `90` | Lifetime of a host token before it must be renewed |

On the Mac (a `/etc/palabre-apple-worker.toml`, owned by root, with no secret: the token lives in `token_file`, a separate file with mode 600 owned by the worker user):
`backend_url`, `token_file` path, `image` digest (must equal the server's), `max_vms`,
the blocked ranges of the network section.

## Tooling to install on the Mac

One-time, by hand or with a script in `deploy/apple-host/` (idempotent, `set -eu`):

- macOS (Apple silicon, current), automatic sleep off, FileVault compatible, a non-admin `palabre` user
  for the worker, firewall on.
- Xcode command line tools, **Tart**, **Packer** (with the Tart plugin), **Softnet**.
- The host worker ([Mac builder](apple-host.md): a Python script using only the standard library, run by `launchd` as the
  `palabre` user, restarted on failure) and its `pf` anchor.
- A disk with room for the image (about 50-80 GB per Xcode image) and its clones; the worker deletes
  leftover `job-*` VMs and prunes old images.
- No Claude, GitHub or Apple credential, no Apple ID signed in, no Xcode account.

Rollback: stop the worker (`launchctl bootout`), set `APPLE_MODE_ENABLED=false`. Queued jobs end as
`error` with a summary; existing projects keep working as generic projects. Changing an image back is changing
`APPLE_IMAGE` to the previous digest.

## Security review points

Checked against the list of Inès in #mode-apple (her review of this page asked for the enrollment code and the untrusted `apple.toml` rules, now written above): outbound
filtering of the VM (softnet block + `pf`, backend endpoint and internet only), no shared folder (source
by bundle), images pinned by digest, a clean clone per job, signing outside the VM, short-lived job token
scoped to one job, no Claude/GitHub/Apple key on the Mac. Residual risks, accepted: a build can use the
internet freely (data of the project leaves through it, the project's own source is all it can see); the
host worker token is a long-lived credential on the host, limited to the job queue; a hypervisor escape
would reach the host, which is why the host holds nothing worth stealing and sits on its own network.

## Option kept in reserve: CI runners only

The same tools and job model can have a second *executor*: instead of the Mac, a GitHub Actions workflow on
a macOS runner (`workflow_dispatch` with the SHA, results read back through the API). It needs no
machine and no 2-VM limit, but each loop takes 10 to 15 minutes and there is no interactive simulator.
`apple_jobs` records an `executor` (`vm` or `ci`) so it can be built first, as a cheaper start, and the
VM added later without changing the tools. Whether to start there is a separate choice for the boss.

## Task breakdown

Small tasks, with their dependencies (B backend, M MCP, F front, D DevOps, W docs):

1. **W** Merge this page and link it from [Architecture](architecture.md). No dependency.
2. **B** `Project.platform` column, migration, API schema, validation of `APPLE_MODE_ENABLED`, `.palabre/apple.toml` reader. No dependency.
3. **B** `apple_jobs` table, the queue and its states, the timeouts and the heartbeat. After 2.
4. **B** `apple_hosts` table (hashed, revocable token, expiry), `/api/apple-host/*` endpoints with bearer auth and renewal (valid token required), enrollment gated by a one-time code, apple.toml validation and server-side image choice, job tokens, git bundle serving, artifact storage. After 3.
5. **M** The Apple MCP tools and their permissions, the "job ended" event and wakeup, the Apple prompt block. After 3.
6. **F** "Swift / iPhone app" choice at creation, platform shown in Infos, job list with status and screenshots (web). After 2 and 4.
7. **F** The same on the mobile app. After 6.
8. **D** The Packer template of the Xcode base image and the way to publish and pin it by digest. No dependency.
9. **D** The host worker (VM tool behind a single module, token file and renewal), its `launchd` unit and the install script for the Mac. After 4 and 8.
10. **D** Network isolation (softnet, `pf` anchor, DNS) and its automated check from a VM. After 8; Inès reviews it. Done: see [Mac builder](apple-host.md); the check on the real Mac is still to run.
11. **D** The `swift-ci.yml` template (pushed at creation only if the GitHub token has the `workflow` scope, else added by the first task) and the release workflow with the protected environment. After 2.
12. **B/D** End-to-end test on the real Mac with a sample Swift project, and monitoring of the queue. After 5, 9, 10, 11.
