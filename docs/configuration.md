# Configuration

Compose only passes the variables below to the containers (the secrets as files, the rest as
environment); all are optional, in `.env`:

| Variable | Default | What it does |
|---|---|---|
| `PALABRE_VERSION` | the current release | Version of the images; `latest` only with the autoupdate profile |
| `PALABRE_PORT` / `PALABRE_WEB_PORT` | `2710` / `2810` | Ports of the server and web app |
| `PALABRE_BIND` | `127.0.0.1` | Host address the server port is published on; `0.0.0.0` exposes it on every interface in clear HTTP |
| `PALABRE_WEB_BIND` | `127.0.0.1` | Host address the web app port is published on; `0.0.0.0` exposes `/api` on every interface in clear HTTP |
| `COMPOSE_PROFILES` | | `autoupdate` turns automatic updates on |
| `PALABRE_UPDATE_INTERVAL` | `300` | Seconds between update checks |
| `POSTGRES_USER` / `POSTGRES_DB` | `palabre` | Database user and name |
| `TZ` | `UTC` | Time zone, e.g. `Europe/Paris` |
| `DAILY_TIME` | `09:30` | Time of the daily stand-up (weekdays); empty to turn it off |
| `MERGE_REMINDER_MINUTES` | `10` | Minutes a mergeable task waits before the lead is reminded (once) |
| `RELEASE_WAIT_MINUTES` | `5` | Minutes of calm, with no open task, before the lead is told changes wait for a release (once per head SHA) |
| `MAX_CONCURRENT_AGENTS` | `3` | Agents running at the same time, per Claude account |
| `EXTRA_APT_PACKAGES` | | System packages the agents need, e.g. `nodejs npm` (build argument, needs a local build) |

The other settings of `backend/app/config.py` (the variable is the field name in upper case) keep
their default unless you add them to the `environment:` of the `backend` service in `docker-compose.yml`:

| Variable | Default | What it does |
|---|---|---|
| `SESSION_TTL_SECONDS` | `43200` | Lifetime of the session tokens the apps get by logging in with the `ADMIN_TOKEN` (`POST /api/auth/session`, 12 h); the apps ask for the `ADMIN_TOKEN` again once it ends. Changing the `ADMIN_TOKEN` revokes every session |
| `DEVICE_SESSION_TTL_SECONDS` | `2592000` | Lifetime of a mobile device session (`POST /api/auth/devices`, 30 days). It slides: each use renews it (written at most once a minute), so a phone used at least once in that time never asks for the `ADMIN_TOKEN` again. Revoking a device (`DELETE /api/auth/devices/{id}`) or changing the `ADMIN_TOKEN` cuts it at once. The web session (`SESSION_TTL_SECONDS`) is unchanged |
| `AUTH_MAX_FAILURES` / `AUTH_FAIL_WINDOW_SECONDS` | `10` / `300` | Failed authentications from one IP within the window before it gets `429` |
| `TRUSTED_PROXY_HOSTS` | `["web"]` | JSON list of hosts whose `X-Real-IP` is believed (the web container's nginx) |
| `CORS_ORIGINS` | the Vite dev server (`localhost:1420`) | JSON list of origins allowed to call the API from a browser. The web app (nginx proxy) does not need it; add an origin only to serve a front from elsewhere |
| `IDLE_MINUTES` | `30` | Quiet minutes before the scribe is asked to update a room document |
| `IDLE_MIN_MESSAGES` | `5` | New messages since the last scribe wakeup needed to wake it again (the daily stand-up updates the document anyway) |
| `IDLE_TASK_MINUTES` | `10` | Minutes a task may stay still (or wait for its dev to start) before the lead is alerted |
| `LEAD_DEBOUNCE_SECONDS` | `30` | Window in which changes of a task are grouped into one lead wakeup |
| `CI_MISSING_MINUTES` | `10` | Minutes after a submission without any CI check before the PR goes back to its dev |
| `APPLE_MODE_ENABLED` | `false` | Exposes the Mac builder routes (`/api/apple-hosts`, `/api/apple-enrollment-codes`, `/api/apple-host/*`, see [Apple mode](apple-mode.md)); when off they answer `404` |
| `APPLE_MAX_VMS` | `2` | Build jobs running at once (1 or 2: Apple's limit per Mac); a claim gets nothing while all slots are busy |
| `APPLE_JOB_TIMEOUT_SECONDS` | `1800` | Time after which a running job ends as an infra error (`error`) and its job token is revoked |
| `APPLE_HEARTBEAT_TIMEOUT_SECONDS` | `60` | Silence after which a Mac shows as disconnected and its running jobs end as infra errors |
| `APPLE_HOST_TOKEN_TTL_DAYS` | `90` | Lifetime of a Mac builder's token, from its registration |
| `APPLE_LOG_EXCERPT_CHARS` | `20000` | Characters of the log tail kept with a job's result (the Mac may send more, only the end is stored) |
| `APPLE_ENROLLMENT_CODE_TTL_SECONDS` | `900` | Lifetime of a Mac enrollment code (one use), returned by the API as `ttl_seconds` |
| `APPLE_ENROLL_MAX_ATTEMPTS` | `10` | Enrollment attempts one IP may make per window; beyond that the answer is `429` |
| `APPLE_ENROLL_WINDOW_SECONDS` | `60` | Window of the enrollment attempt limit |
| `STALLED_TASK_MINUTES` | `5` | Minutes a task in progress may stay without any run or wakeup before its dev is woken up again |
| `MAX_STALLED_RESTARTS` | `3` | Times a dev is woken up again after a run that ended without submitting; the lead is told past it |
| `REVIEW_SILENCE_MINUTES` | `15` | Minutes a task in review may wait for a reviewer's verdict before the reviewer is woken up again and the lead told |
| `MAX_REVIEW_REMINDERS` | `3` | Reminders (watchdog and QA/security reports alike) a silent review gets per head SHA; the lead is told once past it |
| `MAX_REVIEW_ROUNDS` | `3` | Rounds of "changes requested" on a task before the lead has to step in |
| `MAX_RUNS_PER_CONVERSATION_HOUR` | `20` | Chatter runs per employee per hour before their wakeups are held |
| `CLAUDE_MAX_TURNS` | `20` | Turn limit (`claude --max-turns`) of a conversation run |
| `CLAUDE_TASK_MAX_TURNS` | `100` | Turn limit of a task run |
| `AGENT_TIMEOUT_S` | `1800` | Seconds before a run is stopped |
| `TEAM_SELECTION_TIMEOUT_S` | `120` | Seconds before the model call that picks the roles of an automatic team is abandoned (the catalog order is used instead) |
| `AGENT_POOL_SIZE` | `8` in the image, `0` otherwise | Number of per-run system users `<AGENT_USER>1..N`. A run holds one for its whole life (it waits if all are taken), so concurrent runs never share a uid and cannot read each other's `/proc/<pid>/environ` (MCP token, Claude tokens). `0`: every run shares `AGENT_USER`. The build argument of the same name sets how many accounts the image creates |
| `AGENT_USER` | `agent` in the image | System user the agents' `claude` runs as, through `sudo`. Empty: agents share the backend's user (local dev), with a warning at startup |
| `CONTEXT_RESET_EVERY_TASKS` | `5` | Tasks an employee takes part in when they end (merged or cancelled: as assignee, reviewer, QA or security reviewer, or as the one who merged or cancelled it; counted once per task) before their next run starts on a blank context: their Claude sessions are no longer resumed. `0` turns it off. Notes, tasks, room documents and chat are kept, and a run in progress is never cut |
| `CONTEXT_RESET_EVERY_RUNS` | `5` | Runs a single Claude task session (for one employee) serves before the next run on that subject starts a new session instead of resuming it. Conversation wakeups never resume: each starts a new session, as the prompt cache has expired between two wakeups. The employee's other sessions are untouched, and it works next to `CONTEXT_RESET_EVERY_TASKS`. `0` turns it off. A run in progress is never cut |
| `EGRESS_ALLOWED_HOSTS` / `EGRESS_ALLOWED_PORTS` | npm, PyPI and Go registries, `statsig.anthropic.com` / `[443]` | JSON lists of what the agents' egress proxy may reach, see [Security](security.md) |
| `EGRESS_MAX_TUNNELS` | `64` | Concurrent tunnels of the egress proxy |
| `ANTHROPIC_ALLOWED_PATHS` / `ANTHROPIC_ALLOWED_SERVER_TOOLS` | `v1/messages`, `v1/messages/count_tokens` / `web_search` | JSON lists of what the Anthropic reverse proxy forwards |
| `ANTHROPIC_MAX_BODY_BYTES` / `ANTHROPIC_TIMEOUT_S` | `67108864` (64 MiB) / `600` | Largest request body (bytes) and seconds before a request to the Anthropic reverse proxy is cut |
| `DATABASE_URL` | `postgresql+asyncpg://palabre:palabre@localhost:5432/palabre` | Database URL. When set explicitly (external database) it wins; otherwise, with a `POSTGRES_PASSWORD`, it is built from `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST` and `POSTGRES_DB` |
| `POSTGRES_PASSWORD` / `POSTGRES_HOST` | secret file / `db` | Database password (a secret read from a file, at least 32 characters, never an environment variable) and host used to build `DATABASE_URL` |
| `GITHUB_TOKEN` | | Secret read from a file. Used by the backend only (push, pull requests, merges), never given to agents |
| `CLAUDE_CODE_OAUTH_TOKENS` | | Secret read from a file: one Claude token per account, separated by `\|`; the employees are spread over the accounts |
| `CLAUDE_BIN` | `claude` | Command that launches the agents' Claude Code |
| `PROJECTS_DIR` / `RUNTIME_DIR` | `/data/projects` / `/data/runtime` | Local clones of the projects and temporary files of runs (MCP configs), kept outside the repositories |
| `TOOLCHAINS_DIR` | `/data/toolchains` | Where the toolchains installed for the whole team live |
| `CLAUDE_STORE_DIR` | `CLAUDE_CONFIG_DIR` | The backend's private store of Claude sessions, one directory per employee |
| `AGENT_RUN_DIR` | `/data/run` | Holds the MCP configs of runs when the agent user must read them (`RUNTIME_DIR` is the backend's only) |
| `EGRESS_PROXY_PORT` | `3128` | Port of the local CONNECT proxy through which agents reach the Internet |
| `ANTHROPIC_PROXY_URL` / `ANTHROPIC_API_URL` | `http://127.0.0.1:8000/anthropic` / `https://api.anthropic.com` | Local reverse proxy Claude Code talks to (it holds the account token) and the Anthropic API it forwards to |
| `ANTHROPIC_MAX_BODY_BYTES` / `ANTHROPIC_TIMEOUT_S` | `67108864` / `600` | Largest request body and timeout of the Anthropic reverse proxy |
| `MCP_URL` | `http://127.0.0.1:8000/mcp/` | MCP server URL, as seen from the `claude` processes (in the backend container) |
| `ORCHESTRATOR_ENABLED` | `true` | Turns the orchestrator (wakeups, scheduler) on or off |
| `POLL_INTERVAL_S` | `2.0` | Seconds between two polls of the orchestrator |
| `REVIEW_SILENCE_MINUTES` | `15` | Minutes a task in review may wait for a reviewer's verdict before the reviewer is woken up again and the lead told |
| `EGRESS_FILTER` | `on` | Read by the entrypoint, not by `config.py`: `off` runs without the agents' firewall |

This list is not exhaustive: the settings that only wire the container (database URL and host, directories,
proxy URLs and ports, `MCP_URL`, `CLAUDE_BIN`, `ORCHESTRATOR_ENABLED`, `POLL_INTERVAL_S`...) are set by the
image and rarely need changing; read `config.py` for them.

The lead and devops can also install toolchains for the whole team on their own (`install_toolchain`,
`name` + optional `version`; no root, they live in `/data/toolchains` and survive redeployments).
Each tool has a default version and accepts an exact one; an unknown version is refused with a clear error.

| Name | Default | Accepted versions | Commands |
|---|---|---|---|
| `node` | `lts` | `latest`, a major (`20`), exact | `node`, `npm`, `npx`, `corepack` |
| `go` | `stable` | a minor (`1.22`), exact | `go`, `gofmt` |
| `rust` | `stable` | exact (`1.80.0`) | `rustc`, `cargo`, `rustdoc` (no C linker in the image) |
| `java` | `lts` (Temurin JDK) | a major (`21`) | `java`, `javac`, `jar` |
| `maven` | `latest` | a major, minor or exact | `mvn` (needs `java`) |
| `gradle` | `latest` | exact (`8.10.2`) | `gradle` (needs `java`) |
| `kotlin` | `latest` | exact (`2.0.21`) | `kotlinc`, `kotlin` (needs `java`) |
| `deno` | `latest` | exact | `deno` |
| `bun` | `latest` | exact | `bun` |
| `dotnet` | `lts` | `latest`, a channel (`9.0`), an exact SDK (`9.0.100`) | `dotnet` |
| `zig` | `latest` | a minor (`0.13`), exact | `zig` |
| `terraform` | `latest` | exact | `terraform` |
| `kubectl` | `stable` | a minor (`1.30`), exact | `kubectl` |
| `helm` | `latest` | exact | `helm` |
| `uv` | `latest` | exact | `uv`, `uvx` |

Ruby and PHP are not offered: they have no official prebuilt Linux binaries. Archives come from the
official sites only (nodejs.org, go.dev, static.rust-lang.org, Adoptium, Apache, services.gradle.org,
GitHub releases of the project, dotnet, ziglang.org, HashiCorp, dl.k8s.io, get.helm.sh) and are checked against
their published checksum before extraction. Each version lives in its own directory
(`/data/toolchains/<name>-<version>`), extracted aside and renamed at the end, so a failed download never
leaves a half install; installing another version only moves the links. Their caches (`~/.cargo`,
`~/.m2`, `~/.gradle`...) are in the run's own `HOME`, so they are not kept between runs.
To roll back, install the previous version again (it is still on disk, nothing is downloaded).

The lead and devops can also install a shared
Python venv (`install_toolchain python`, with `packages`, e.g. `pytest pytest-asyncio==0.23.0`).
The venv lives in `/data/toolchains/python-venv`, sees the image's packages, and its `python`,
`pip` and commands (`pytest`...) come first in the agents' `PATH`, so `python -m pytest` still works
after a redeployment. Agents only read the toolchains: packages are installed by the server, from
PyPI, and the tool takes plain names with an optional version (no option, URL or path). Call it
again to add packages. Only wheels are installed (no build step runs as the server), the venv is only writable by the server (a venv agents could write in is recreated), and no pip cache is kept. After a base
image upgrade to another Python minor, the venv is recreated by the next `install_toolchain python`.
