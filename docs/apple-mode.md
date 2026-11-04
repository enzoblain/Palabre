# Apple mode

Apple mode lets the team build iPhone apps in Swift. The agents stay on our Linux servers; a dedicated
Apple-silicon Mac only **compiles and tests** inside throw-away macOS virtual machines (VMs). This page
fixes the structure; nothing described here is implemented yet (see [Task breakdown](#task-breakdown)).

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
  `test_plan`), read by the backend from the task branch. Without it the tools answer with the expected
  file, so an agent can add it itself;
- the apple mode must be enabled on the server (`APPLE_MODE_ENABLED`) and a host worker enrolled; otherwise
  project creation with `platform=apple` is refused with a clear error.

## Running a build or a test

Agents never talk to the Mac. They use MCP tools (listed in the catalog and `permissions.py`):

| Tool | Who | What |
|---|---|---|
| `apple_build` | dev, QA | Queues a build of the task's branch (current head); returns a job id |
| `apple_test` | dev, QA | Same, then runs the tests (`xcodebuild test`, optional `test_plan`, optional screenshots) |
| `apple_job` | dev, QA, reviewer | Status (`queued` with its position, `running`, `passed`, `failed`, `error`, `timeout`, `cancelled`), summary and failed tests |
| `apple_job_logs` | dev, QA, reviewer | A page of the log (the tail by default), so a run never loads a huge log |
| `apple_cancel` | dev, QA | Cancels a queued or running job of the caller's own task |

Jobs are asynchronous: an agent run is not kept waiting for a queue slot. The tool returns at once; when
the job ends, the backend posts a short system message in the task room and wakes the agent that queued
it (a new event type next to the CI events in `orchestrator/events.py`). A job is tied to the task and
to the head SHA it built, so a verdict on an old commit is never shown as current.

A result holds: the status, the duration, build errors and warnings parsed from `xcodebuild`, the failed
tests (name, message, file:line from the `.xcresult`), the log, and optional simulator screenshots. The
backend stores them in the database (summary) and in `APPLE_ARTIFACTS_DIR` (log, screenshots, kept
`APPLE_ARTIFACT_RETENTION_DAYS`). Screenshots are served by the API so the front and the mobile app can
show them; agents get their URL, never a path.

## Backend ↔ Mac

### Protocol

Pull model over HTTPS, using endpoints under `/api/apple-host/` (separate from the agents' MCP server and
from the apps' API, with their own auth):

1. `POST /api/apple-host/claim`: the host worker long-polls (about 25 s) and receives at most one job if
   fewer than `APPLE_MAX_VMS` VMs run. The job holds the commit, the `apple.toml` content, the Xcode image
   to use and a **job token**.
2. The worker clones the pinned image, starts the VM and passes it the job token and the backend URL (see
   below), then waits for it.
3. The VM downloads the source, builds, and uploads the logs and results with the job token.
4. The worker sends `POST /api/apple-host/jobs/{id}/finish` (exit status) and runs `tart delete`. If the
   VM exceeds `APPLE_JOB_TIMEOUT_SECONDS`, the worker kills and deletes it, and the job ends as `timeout`.
5. The worker sends a heartbeat every 15 s. A job whose worker went silent for `APPLE_HEARTBEAT_TIMEOUT_SECONDS`
   is marked `error` and its slot freed (the VM is deleted at the worker's next start, which wipes every
   VM that is not in its list of live jobs).

### Authentication, with no long-term secret on the VM

Two different credentials, with a different scope each:

- **Host worker credential** (on the Mac host, never in a VM): a client certificate issued by the backend
  at enrollment (`mTLS`, or a bearer token if the Mac sits behind the existing reverse proxy; the
  certificate is preferred because it never travels in a header). It can only call `/api/apple-host/*`:
  claim a job, send heartbeats, finish a job. It cannot read a project, a conversation or call GitHub.
  It is revocable from the server (and expires: 90 days, renewed by the worker). It is the only
  long-lived credential involved, it is not one of the three forbidden kinds (Claude, GitHub, Apple), and
  it opens nothing but the job queue.
- **Job token** (the only secret that enters the VM): random, created when the job is claimed, valid for
  that job only, stored hashed, revoked when the job ends or times out, and usable only for three
  things: download this job's source bundle, upload its logs and results, read its own status. Same
  pattern as the agents' run tokens (`mcp_server/run_tokens.py`).

The source never needs a GitHub token on the Mac: the backend, which already holds the token and a clone
of each project (`worktrees.py`), builds a `git bundle` of the task branch at the job's SHA and serves it
at the one-time URL guarded by the job token. The VM unpacks it into its own disk.

## Virtual machines

### Tool and image

- **Tart** (Apple Virtualization framework, Apple silicon, runs macOS guests, APFS copy-on-write
  clones). Alternatives (Anka, UTM) are paid or not scriptable enough; Tart is open source and widely used
  in CI. Apple's license limits a Mac to 2 macOS VMs at once, which `APPLE_MAX_VMS=2` reflects.
- **Base image**: built by us with Packer from a Cirrus Labs macOS base image, with a given Xcode, its
  simulators, `xcbeautify`, Ruby/`bundler`, SwiftLint, and an autostarted *job runner script* (a shell
  script, no daemon) that reads the job from the guest metadata and does the steps of step 3 above.
  The image contains no credential. It is **pinned by digest** (`APPLE_IMAGE`, `name@sha256:...`), never
  by tag; updating Xcode means building a new image, testing it, then changing the digest (one commit, one
  config change, revertible).
- **One clone per job**: `tart clone <digest> job-<id>`, `tart run`, `tart delete`. A VM is never
  reused or reset in place, so a project cannot leave anything for the next one.

### Network isolation

The risk (raised by Inès): SwiftPM plugins and Xcode "Run Script" phases run arbitrary code at build
time, and by default Tart's NAT lets a VM reach the host and the LAN. So:

- VMs run with Tart's **softnet** (`--net-softnet`), with `--net-softnet-block` on the private ranges
  (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `100.64.0.0/10`, loopback/multicast),
  which covers the host and the LAN. The backend is reached through its public (or tunnel) address, which
  is allowed explicitly by `--net-softnet-allow` when the server is on a private address.
- A **second layer** on the host: a `pf` anchor loaded at boot that applies the same rules to the VM
  interface. A softnet bug must not be enough to reach the LAN.
- The VM uses a public DNS resolver, not the host's.
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

The queue is the `apple_jobs` table (`queued → running → passed|failed|error|timeout|cancelled`), no
extra broker. A job is claimed with `SELECT ... FOR UPDATE SKIP LOCKED`, only if fewer than
`APPLE_MAX_VMS` jobs run. Order: first in, first out, with at most `APPLE_MAX_QUEUED_PER_PROJECT` waiting
jobs per project and a newer job on the same task replacing a still-queued one (an old SHA is useless).
A job that waits more than `APPLE_QUEUE_MAX_WAIT_SECONDS` ends as `error`. The queue length and the
wait time are shown in monitoring, so the boss can see when 2 VMs are not enough.

## CI, signing and publication

- **PR checks for a Swift project**: a workflow template (`.github/workflows/swift-ci.yml` in the project,
  added by the creation of an `apple` project) runs `xcodebuild test` on a pinned macOS runner image. It
  has no secret and `contents: read` only. The "CI must be green to merge" rule applies as for any
  project; the VM job gives the agents their fast loop, the CI is the check of record. (GitHub macOS
  minutes cost more than Linux ones; the workflow only runs on PRs, with concurrency cancelation.)
- **Signing and publication** happen only in GitHub Actions, on a version tag, in a protected environment
  limited to `v*` tags (the pattern of `mobile-release.yml` and
  [Mobile release](mobile-release.md)): certificate, provisioning profile and App Store Connect key live
  in that environment's secrets, never in the repository, a VM or the Mac. The workflow archives, signs
  and uploads to TestFlight. The simulator build used by the VMs needs no signing.
- The agents never see signing secrets. Releasing stays the lead's `merge_release` step.

## Configuration

To add to `backend/app/config.py` and [Configuration](configuration.md) (all optional, off by default):

| Variable | Default | What it does |
|---|---|---|
| `APPLE_MODE_ENABLED` | `false` | Allows `platform=apple` projects and exposes `/api/apple-host/*` and the Apple tools |
| `APPLE_MAX_VMS` | `2` | VMs running at once (Apple's limit per Mac; never above 2) |
| `APPLE_IMAGE` | | Image to clone, pinned by digest; refused if it has no `@sha256:` |
| `APPLE_JOB_TIMEOUT_SECONDS` | `1800` | Maximum duration of a job before the VM is killed |
| `APPLE_HEARTBEAT_TIMEOUT_SECONDS` | `60` | Silence of the host worker after which its jobs are in error |
| `APPLE_QUEUE_MAX_WAIT_SECONDS` | `1800` | Wait in the queue before a job ends in error |
| `APPLE_MAX_QUEUED_PER_PROJECT` | `3` | Waiting jobs a project may have |
| `APPLE_ARTIFACTS_DIR` | `/data/apple-artifacts` | Where logs and screenshots are stored |
| `APPLE_ARTIFACT_RETENTION_DAYS` | `14` | Age after which logs and screenshots are deleted |
| `APPLE_LOG_MAX_BYTES` | `20971520` | Size beyond which a log is cut (the tail is kept) |
| `APPLE_HOST_CERT_FINGERPRINTS` | `[]` | JSON list of the enrolled host worker certificates (managed by the enrollment endpoint) |

On the Mac (a `/etc/palabre-apple-worker.toml`, owned by root, no secret except the host certificate path):
`backend_url`, `client_cert` / `client_key` paths, `image` digest (must equal the server's), `max_vms`,
the blocked ranges of the network section.

## Tooling to install on the Mac

One-time, by hand or with a script in `deploy/apple-host/` (idempotent, `set -eu`):

- macOS (Apple silicon, current), automatic sleep off, FileVault compatible, a non-admin `palabre` user
  for the worker, firewall on.
- Xcode command line tools, **Tart**, **Packer** (with the Tart plugin), **Softnet**.
- The host worker (a single Python script using only the standard library, run by `launchd` as the
  `palabre` user, restarted on failure) and its `pf` anchor.
- A disk with room for the image (about 50-80 GB per Xcode image) and its clones; the worker deletes
  leftover `job-*` VMs and prunes old images.
- No Claude, GitHub or Apple credential, no Apple ID signed in, no Xcode account.

Rollback: stop the worker (`launchctl bootout`), set `APPLE_MODE_ENABLED=false`. Queued jobs end as
`cancelled`; existing projects keep working as generic projects. Changing an image back is changing
`APPLE_IMAGE` to the previous digest.

## Security review points

Checked against the list of Inès in #mode-apple (to be confirmed by her review of this page): outbound
filtering of the VM (softnet block + `pf`, backend endpoint and internet only), no shared folder (source
by bundle), images pinned by digest, a clean clone per job, signing outside the VM, short-lived job token
scoped to one job, no Claude/GitHub/Apple key on the Mac. Residual risks, accepted: a build can use the
internet freely (data of the project leaves through it, the project's own source is all it can see); the
host worker certificate is a long-lived credential on the host, limited to the job queue; a hypervisor escape
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
4. **B** `/api/apple-host/*` endpoints, enrollment, job tokens, git bundle serving, artifact storage. After 3.
5. **M** The Apple MCP tools and their permissions, the "job ended" event and wakeup, the Apple prompt block. After 3.
6. **F** "Swift / iPhone app" choice at creation, platform shown in Infos, job list with status and screenshots (web). After 2 and 4.
7. **F** The same on the mobile app. After 6.
8. **D** The Packer template of the Xcode base image and the way to publish and pin it by digest. No dependency.
9. **D** The host worker, its `launchd` unit and the install script for the Mac. After 4 and 8.
10. **D** Network isolation (softnet, `pf` anchor, DNS) and its automated check from a VM. After 8; Inès reviews it.
11. **D** The `swift-ci.yml` template and the release workflow with the protected environment. After 2.
12. **B/D** End-to-end test on the real Mac with a sample Swift project, and monitoring of the queue. After 5, 9, 10, 11.
