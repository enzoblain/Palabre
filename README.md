# Palabre

**A company of AI agents that works for you.** Give it a GitHub repository and a
software team builds your product: a lead organizes the work, developers open pull
requests, reviewers and QA check them before anything is merged. Or give it a topic
and a research group searches the web, debates and writes you a sourced report.

You are the CEO. You talk to your team in chat rooms, like you would on Slack, from a
desktop app or your phone's browser. The agents run on [Claude Code](https://claude.com/claude-code),
billed on your Claude subscription, on a server you host yourself (a NAS is enough).

- [How it works](#how-it-works)
- [Install the server](#install-the-server)
- [Use the apps](#use-the-apps)
- [Configuration](#configuration)
- [Security](#security)
- [Develop](#develop)

## How it works

### Software company

You create a project on a GitHub repository and pick a company size. Each employee gets
a name, a role and a personality drawn at random (risk-taking, taste for new technologies,
speed vs quality...), or you build the team yourself.

| Size | People | Rules before a merge |
|---|---|---|
| Startup | 4 | One review approval |
| Scale-up | 8 | One review approval and a QA pass |
| Enterprise | 12 | Plus security on sensitive PRs, and a green CI |
| Multinational | 16 | Two approvals, QA, security, CI, updated docs (README or `docs/`), and your validation of every decision |

You only talk to the lead, in `#direction`: it is the one channel you can write in, and
it holds only you and the lead. The team works in its own channels (`#general`,
`#engineering`...) and the lead can open more (`create_channel`: `#backend`, `#front`...).
You read every channel live but they are read-only for you (the API refuses your messages
there), and only the lead is woken by what you post. The lead relays between direction and
the team. Existing projects get their `#direction` channel at startup; their rooms become
team channels.

From there the team works on its own:

1. **The lead** splits the work into tasks with acceptance criteria and assigns them.
2. **A developer** works on the task in its own git clone (made from the project's clone with `--reference --dissociate`, so it never writes to it; the token never reaches a clone: GitHub is fetched and pushed from the project's clone, and agent clones only talk to it locally), then opens a pull request. The branch starts as `task/<id>` and, at the first
   `submit_for_review`, is renamed `<type>/<id>-<slug>` (`feat/60-show-real-claude-usage`) from the title below, before the push.
   Everything that goes to GitHub is in English, whatever the team's language, in
   [Conventional Commits](https://www.conventionalcommits.org) format: the developer gives
   `submit_for_review` a title such as `feat(usage): show real Claude usage per model`, the backend
   refuses a non-conforming one and adds the PR number once the PR is open (`... (#82)`; never the task number, which GitHub would read as another PR). That title is the PR's and
   the squash commit's; the PR body says `Palabre task #60`. Review and QA comments and release notes are in English too (release notes keep the standard text, not Conventional Commits bullets).
3. **Reviewers, QA and security** read the diff and approve or request changes, as the
   company's rules require.
4. **The lead** merges once every rule is met. Nothing reaches the project's branch otherwise.

The platform keeps the lead on track. Every step of a task (pull request submitted, each
review, QA or security verdict with its author, merge) is announced by a short "Palabre"
line in the task's channel, with the link. As soon as a task meets every merge rule of the
company's size, the lead is woken up to merge it,
and reminded once if it is still not merged after `MERGE_REMINDER_MINUTES` (10 by default).
The same goes for releases: when the CI of the open release PR (team's branch to production) ends,
and, after `merge_release`, when the CI of production's head ends, the lead is woken up once per
head SHA with the result (green, or the failing checks) and a "Palabre" line is posted in the
team's first channel. Green means `merge_release`, then `publish_version`: once production's CI is green, the wakeup says which version to publish ("publish vX.Y.Z").
No release depends on the lead remembering it: when the team's branch holds commits production lacks, no task is open and nothing moved for `RELEASE_WAIT_MINUTES` (5 by default), the lead is woken (`release_pending`, once per head SHA, stored in `Project.release_reminded_sha`) with the pending changes and the computed version.

A resubmission whose content is unchanged (the reviewed commit replayed with `git merge-tree` on the base the branch now sits on gives exactly the new tree, i.e. a pure rebase) keeps the review round and its approvals, unless a reviewer's latest verdict of the round asks for changes or the task newly becomes sensitive; the merge still waits for the CI of the new head. A pure rebase keeps the approvals even if the new base changes the behavior indirectly; the CI on the new head is then the only safeguard. Any content change starts a new round and drops every approval. The `refs/palabre/reviewed/{id}` ref that pins the reviewed commit is deleted when the task is merged or cancelled.

A task stuck in review does not wait for someone to notice: if its PR conflicts with the team's
branch, if no CI check is reported `CI_MISSING_MINUTES` (10 by default) after the submission, or if
the CI is red on an otherwise approved task, the task goes back to its dev (`changes_requested`)
with the problem (rebase, missing CI, failing checks) and a "Palabre" line is posted in the team's
first channel. The dev is woken up once per head SHA. A red CI only sends the task back once it is
otherwise approved (no other merge rule is missing); before that, reviewers go first.
A red check comes with its annotations and summary, framed as untrusted CI output (at most 20 annotations and 4,000 characters, plain text, fetched by the backend; agents never see the token), in `merge_blockers`, the dev's wakeup and the lead's wakeups; the team channel only gets the first line.

The lead is also woken up (`task_update`) whenever a task moves: PR submitted or resubmitted, each
review verdict, CI finished, task sent back. Changes of the same task within
`LEAD_DEBOUNCE_SECONDS` (30 by default) are grouped into one wakeup sent when the window ends, listing them all. A watchdog alerts the lead
(`task_idle`, once per head SHA) when a task in progress or in review has not moved for
`IDLE_TASK_MINUTES` (10 by default), with the reason: conflict, missing or red CI, missing review,
or simply no activity.

A task never waits silently for its dev either: putting a task back to `todo` (with or without a PR:
rebase, new work), requesting changes, or calling `assign_task` (also to the same dev, which then
only nudges) wakes the assignee with the reason, unless a run or a wakeup is already on that
task. A `todo` or `changes_requested` task whose dev has had no run for `IDLE_TASK_MINUTES` is
nudged once; if it still does not start after another `IDLE_TASK_MINUTES`, the lead is alerted
(`task_idle`). Tasks waiting for their dependencies are left alone. When `merge_task` is refused
because the CI is still running, the lead is woken (`merge_retry`) as soon as the CI is over,
or as a mergeable task if every rule is then met.

Finished tasks clean up after themselves: once a task is merged or cancelled, the backend
closes its PR if still open and deletes its branch (`task/<id>...` or `<type>/<id>-<slug>`, on GitHub) and its
clone. Only branches recorded on tasks are touched, never the default branch, `dev` or a
release PR. To clean the backlog, call `POST /api/tasks/cleanup` (admin token): it is idempotent
and GitHub errors (404...) are only logged.

Agents that keep pinging each other are throttled: past `MAX_RUNS_PER_CONVERSATION_HOUR` (default 20)
executed chatter runs of one employee within an hour, across all their conversations (skipped
wakeups do not count), the lead is alerted. Their chatter wakeups (mentions...) are not lost:
they stay queued and run grouped in one run once the window frees a slot. The boss posting in a
conversation lifts the limit there, or call `POST /api/conversations/{id}/lift-rate-limit` (admin
token, `204`): earlier runs stop counting and held wakeups of that conversation run right away
(those held in other conversations keep waiting). The reset is kept in memory, so a backend restart forgets it.

Along the way the team holds a daily stand-up, records decisions in each room's shared
document, and asks you when something is yours to decide. There is no inbox: the lead puts
what waits for you in the direction channel as a request, a message with three answers,
Validate, Reject or Nuance (a free comment, required). You answer once; the answer shows
in the thread and wakes the lead up with your comment (`POST /api/messages/{id}/answer`).
Proposed decisions, releases and escalations to the boss become such requests on their own,
and the lead can ask for anything else with `ask_ceo`. A research group has no direction
channel: its decisions are only in the room document. On upgrade, what waited in the old
inbox is turned into requests in direction.

A new project works on a `dev` branch, created from the repository's default branch if
missing (an empty repository gets its default branch, `main` unless GitHub says otherwise, then `dev`, from a first commit with a minimal README and `.gitignore`). The production branch is the one GitHub declares as default (`main`, `master` or another; failing that `main`, then `master`), never assumed. Every agent is told to read the README and the tree of the team's branch first, and every
task's pull request targets it. Only a release reaches production. To switch an existing
project, point it at `dev` in the settings, or ask the lead to run `set_working_branch`
(`dev`); open pull requests are retargeted. When a step is ready, the lead opens the pull
request from `dev` to production and asks you in direction: Validate merges it, Reject closes
it, Nuance leaves it open for the lead to rework. The lead never merges into the
repository's default branch: that one is yours.

The lead can also deliver alone. `merge_release` merges the release pull request once CI is
green on it, whatever the company size, and only if the PR has not moved since (a task
merged meanwhile makes GitHub refuse), and tells you in direction, with nothing to answer; `publish_version`
tags the head of the default branch `vX.Y.Z` (CI must be green on it) and publishes the GitHub Release (named `Palabre vX.Y.Z`, with the changes since the previous tag grouped by type, then the download text of the release
workflow), which starts that workflow; `fix_release` regenerates the name and notes of an existing release the same way. The sections are Breaking Changes, Features (`feat`), Bug Fixes (`fix`), Performance (`perf`), Documentation (`docs`) and Other (everything else, old non-conventional commits included), one `scope: description (#PR)` line per commit. Versions follow [Semantic Versioning 2.0.0](https://semver.org), computed from the
Conventional Commits merged since the last `vX.Y.Z` tag: `fix` and `perf` bump the patch, `feat` the minor,
a `!` or a `BREAKING CHANGE` footer the major (while in 0.x, a breaking change bumps the minor); the highest bump
wins. The lead's and DevOps's prompts state the rule. `publish_version` refuses a version that is not `X.Y.Z`, a tag that
already exists, or a version that differs from `frontend/package.json`, its lock, `tauri.conf.json`, `Cargo.lock` or
`Cargo.toml` (the bump is made for you). Releases need no bump task: `merge_release` first computes the next version with the rule above from the commits since the last tag, and the backend commits `chore(release): X.Y.Z` on the team's branch only (never on production, no force push), in one commit made in its local clone: `frontend/package.json` and `package-lock.json`, `tauri.conf.json`, `Cargo.toml`, `Cargo.lock` (edited directly, no npm or cargo on the server), and the Keep a Changelog entry under `[Unreleased]` (it replaces whatever `[Unreleased]` held, and any entry of a version never released: nobody edits the CHANGELOG by hand, the developers' prompts say so; `feat` Added, `fix` Fixed, `perf` and `refactor` Changed, breaking changes flagged; chores and docs are left out). It is recomputed on every call (a commit merged after the bump joins the entry, and the version follows the bump level) and commits only if a file changes, never an empty commit. It refuses a version file whose format it does not know. After a commit the release PR's CI restarts: the lead is woken once it ends, then calls `merge_release` again, which merges under the usual CI gate. Both tools are the lead's only (`ship_release` permission in
the catalog); `propose_release` and Validate stay available when the lead wants your opinion.

The lead also triages pull requests no task owns, such as Dependabot's: `list_pull_requests`
shows every open one, and `close_pull_request` closes one with a comment and deletes its
branch. It refuses a task's pull request (cancel the task instead) and the release one, and
never deletes production, the team's branch or a fork's branch, nor a branch named like a task's (`feat/12-foo`).

### Research group

You give a topic instead of a repository. A group of peers of equal standing, each with
their own angle (explorer, skeptic, data analyst, devil's advocate, historian...), works
on every question you ask in four phases:

1. **Research**: everyone searches the web and posts sourced findings.
2. **Debate**: they confront their findings.
3. **Conclusion**: each one states a final position.
4. **Report**: the rapporteur writes it up: the short answer, the key findings with their
   sources, the disagreements and the open questions.

Groups come in three sizes: Duo (2), Panel (5) and Council (9). You choose the rapporteur,
or leave it to chance.

### Architecture

```
 Desktop app ─────────────────► :2710  Server (FastAPI) ──── PostgreSQL
 Phone / browser ──► :2810  Web app (nginx) ─┘    │
                                                  ├── Orchestrator: wakes agents up on events
                                                  ├── claude -p runs, one per agent wake-up
                                                  └── MCP server: the agents' tools
                                                            │
                                                         GitHub
```

- **Server** (`backend/`): Python, FastAPI, SQLAlchemy. It stores the projects, runs the
  orchestrator, clones the repositories and talks to GitHub.
- **Agents**: each wake-up is a `claude -p` run with the employee's system prompt, built
  from the role catalog (`backend/app/company/catalog.toml`). They act through an MCP
  server whose tools depend on their role: only a lead can merge, only reviewers, QA and
  security can approve a pull request.
- **Apps** (`frontend/`): React and TypeScript, packaged with Tauri for the desktop, and
  served by nginx for the browser.

## Install the server

You need a machine with Docker and Compose (amd64 or arm64), a Claude subscription and,
for software projects, a GitHub token.

```sh
mkdir palabre && cd palabre
curl -fsSLO https://raw.githubusercontent.com/enzoblain/Palabre/main/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/enzoblain/Palabre/main/.env.example -o .env
# Fill in .env (see below), then:
docker compose pull
docker compose up -d
```

Four values in `.env` are required:

| Variable | What it is |
|---|---|
| `ADMIN_TOKEN` | Protects the API; the apps ask for it. At least 32 characters (startup fails otherwise), e.g. `openssl rand -hex 32`. After 10 failed attempts within 5 minutes, an IP gets `429` until the window passes |
| `CLAUDE_CODE_OAUTH_TOKENS` | Run `claude setup-token`. Several accounts: separate their tokens with `\|` |
| `GITHUB_TOKEN` | Fine-grained token on your repositories: Contents and Pull requests (read/write), Checks and Metadata (read) |
| `POSTGRES_PASSWORD` | At least 32 characters: letters, digits, `-` and `_` |

The server listens on port `2710` and the web app on port `2810`.

### Updates

Upgrading from a version before secret files: keep your `.env` as it is, the four secrets are
still read from it. Compose now mounts them as files (`/run/secrets`) instead of environment
variables, so you need Compose 2.30 or later, and any other variable you set must be one of
those listed in [Configuration](#configuration): the container no longer gets the whole
`.env`, so settings like `CORS_ORIGINS`, `CLAUDE_MAX_TURNS`, `AGENT_TIMEOUT_S`,
`IDLE_MINUTES`, `MAX_REVIEW_ROUNDS` or `CI_MISSING_MINUTES` must now be added to the
`environment:` of the `backend` service in `docker-compose.yml`. Recreate the containers: `docker compose pull && docker compose up -d`. Nothing
else changes; Postgres keeps its current password.

Upgrading from a version that accepted short secrets: `ADMIN_TOKEN` and `POSTGRES_PASSWORD` must now
have at least 32 characters, or the backend refuses to start. Generate new values with
`openssl rand -hex 32`. For `ADMIN_TOKEN`, edit `.env` and run `docker compose up -d`. For
`POSTGRES_PASSWORD`, change it in Postgres first, because the database image only reads it when it
creates an empty volume: `docker compose exec db psql -U palabre -c "ALTER USER palabre WITH PASSWORD '<new>'"`,
then put the same value in `.env` and run `docker compose up -d`.

Upgrading from a version before the agent user: nothing to do. The container starts as
root, re-owns the existing `/data` volume once (group `work`, marker `/data/.isolation-v1`),
makes each project's reference clone private to the server, then drops to `palabre`. If
you run the image without Docker's entrypoint, do that `chown`/`chmod` yourself.
After dropping root, the entrypoint execs `tini`: PID 1 is tini running as `palabre`, and it
reaps the orphans of killed agent runs, so `docker run` without Compose needs no `--init`.

```sh
docker compose pull && docker compose up -d
```

Or let Palabre update itself: with `COMPOSE_PROFILES=autoupdate` in `.env`, an `updater`
container checks for a new version every 5 minutes and restarts the server and web app
when one is out. Running agents get 60 seconds to stop cleanly.

Automatic updates are a security trade-off. The `updater` mounts `/var/run/docker.sock`, which
is root on the host, and it only finds new images under a moving tag, so you also set
`PALABRE_VERSION=latest`: a compromised image or registry account would then run on your
machine without anyone choosing it. Leave it off (the default) unless you accept that; by
default every image is pinned (Palabre by version; `postgres`, `docker`, and the Python, Node and nginx bases by digest)
and you update on purpose with the command above.

Claude Code is installed in the image at the version pinned in `backend/Dockerfile`, after its
SHA-256 is checked against the pinned value (taken from Anthropic's release manifest, which is
fetched from the same host as the binary: it protects against drift and corruption, not against
a compromise of that host at the time of the bump). Anthropic does not publish an independent signature we check here.
To bump it, change `CLAUDE_CODE_VERSION` and both checksums together.

## Use the apps

**Desktop app**: download it from the [latest release](https://github.com/enzoblain/Palabre/releases/latest).

- **macOS**: the `.dmg` (`aarch64` for Apple Silicon, `x64` for Intel). The app is not
  signed yet: the first time, right-click it → Open, or run
  `xattr -dr com.apple.quarantine /Applications/Palabre.app`.
- **Windows**: the `.msi` or the `-setup.exe`.
- **Linux**: the `.AppImage`, `.deb` or `.rpm`.

Enter your server's address (e.g. `http://192.168.1.10:2710`) and the `ADMIN_TOKEN`.

**Phone or any browser**: open `http://<your server>:2810` and enter the `ADMIN_TOKEN`.
To reach it away from home, put the server on a private network such as
[Tailscale](https://tailscale.com) rather than exposing it to the internet.

On first launch, set your name in the settings: it is the one your team calls you by.

**Account quota**: `GET /settings/quota` returns, for each Claude account, what `/usage`
shows in Claude Code: the 5-hour session, the week (all models) and the week per model,
each with the percentage used and its reset time. It is read from Claude's OAuth usage
endpoint with the account's token, which never leaves the backend, and cached for about a
minute. An account that fails returns an `error` without affecting the others.
`GET /settings/usage` is different: it only sums tokens and cost of the runs Palabre made.

**Credits exhausted**: when a run fails because the account hit its usage limit or has no
credit left (recognised in the output of `claude -p`, with its reset time when it gives
one, otherwise a 30-minute estimate), the account is paused until then: no new run starts
on it, automatic employees are spread over the other accounts, and the wakeups stay queued
instead of failing (the run does not count as a task failure). The boss gets one line in
#direction per episode ("Claude credits exhausted on account X, work resumes at HH:MM"),
and `GET /orchestrator` lists `exhausted_accounts` for the app. Once the reset has passed
and a run succeeds, the lead is woken with a `credits_back` event (tasks in progress,
queued wakeups) and the boss is told in #direction. The state is kept in memory: after a
restart, the first run that hits the limit rebuilds it.

## Tests

Backend tests (pytest, no database or network needed):

```sh
cd backend && pip install --require-hashes -r requirements-dev.txt && python -m pytest
```

On GitHub Actions, a hook in `tests/conftest.py` prints an `::error` annotation (file, line, test name) for each failed test, so the names show on the PR. GitHub keeps only 10 error annotations per step; the full list is in the log (`-rfE`). The frontend check has no such annotation.

Compose smoke test (needs docker, takes a few minutes):

```sh
.github/scripts/compose-smoke.sh
```

It brings up the real `docker-compose.yml` with throwaway secrets (it writes its own `.env`, removed on exit, and refuses to run over yours or a compose override) and checks that: the API answers 401 without or with a wrong token and 200 with the right one; no secret appears in the backend's `env`, `/proc/1/environ` or `docker inspect`; the `agent` user exists and can read neither `/run/secrets` nor `/run/palabre-secrets`; the version under test starts on a volume used by the last published version (data kept, volume migrated); the agent pool is isolated on the real container (`check-isolation.sh` with `CHECK_POOL_ONLY=1`: two simultaneous runs cannot read each other's `/proc/<pid>/environ` or MCP config, `sudo -l` shows exactly the nine rules (the pool users, plus root for the four `palabre-claim-clone` ones), a `setsid` process left by a run is gone when the account is leased again); and the `updater` recreates the backend with the secrets still resolved. Without a published version (or one older than Docker secrets), the upgrade and updater steps are skipped with a notice. In CI this is the `Compose smoke test` job, run on pull requests and on pushes to `dev` and `main`; failures show as `::error` annotations.

`tests/conftest.py` holds the shared fixtures: `FakeSession` (in-memory stand-in for
`AsyncSession`), object builders (`make_task`, `make_employee`...), `process` (sets the mode's
merge gates) and `fake_github` (replaces the GitHub and git calls). Counting queries can run against an in-memory SQLite session (`aiosqlite`, dev only), see `tests/test_context_reset.py`.

## Dependencies

Backend dependencies are frozen with [pip-tools](https://pip-tools.readthedocs.io) (versions and
hashes). Edit the readable `.in` files, never the generated `requirements*.txt`:

- `backend/requirements.in`: runtime dependencies (installed in the Docker image)
- `backend/requirements-dev.in`: test dependencies, on top of the runtime ones

pip-tools is a dev tool: it is not in the image. Install it where you work (`pip install pip-tools`),
then from `backend/`:

```sh
# Add a dependency: put it in the right .in file, then regenerate both files
pip-compile --generate-hashes --strip-extras requirements.in
pip-compile --generate-hashes --strip-extras requirements-dev.in

# Upgrade one runtime package (or --upgrade for all of them)
pip-compile --generate-hashes --strip-extras --upgrade-package fastapi requirements.in
pip-compile --generate-hashes --strip-extras requirements-dev.in

# Upgrade a test-only package (pytest...)
pip-compile --generate-hashes --strip-extras --upgrade-package pytest requirements-dev.in
```

Always compile `requirements.in` first: the dev file is constrained by it, so both stay on the same
versions. Compile on Linux with Python 3.12 (as the image and the CI): platform markers can differ elsewhere. Commit the `.in` and `.txt` files together.
Installs use `pip install --require-hashes -r ...`.

Dependabot opens a weekly grouped PR on `dev` for the backend locks. How it orders the two
compilations is not guaranteed, so CI installs both locks in one `pip install`: a PR where they pin
different versions fails. If that happens, run the compile commands above by hand.

## Configuration

All optional, in `.env`:

| Variable | Default | What it does |
|---|---|---|
| `PALABRE_VERSION` | the current release | Version of the images; `latest` only with the autoupdate profile |
| `PALABRE_PORT` / `PALABRE_WEB_PORT` | `2710` / `2810` | Ports of the server and web app |
| `COMPOSE_PROFILES` | | `autoupdate` turns automatic updates on |
| `PALABRE_UPDATE_INTERVAL` | `300` | Seconds between update checks |
| `TZ` | `UTC` | Time zone, e.g. `Europe/Paris` |
| `DAILY_TIME` | `09:30` | Time of the daily stand-up (weekdays); empty to turn it off |
| `MERGE_REMINDER_MINUTES` | `10` | Minutes a mergeable task waits before the lead is reminded (once) |
| `RELEASE_WAIT_MINUTES` | `5` | Minutes of calm, with no open task, before the lead is told changes wait for a release (once per head SHA) |
| `CLAUDE_MAX_TURNS` | `20` | Turn limit (`claude --max-turns`) of a conversation run |
| `CLAUDE_TASK_MAX_TURNS` | `100` | Turn limit of a task run |
| `MAX_CONCURRENT_AGENTS` | `3` | Agents running at the same time, per Claude account |
| `AGENT_POOL_SIZE` | `8` in the image, `0` otherwise | Number of per-run system users `<AGENT_USER>1..N`. A run holds one for its whole life (it waits if all are taken), so concurrent runs never share a uid and cannot read each other's `/proc/<pid>/environ` (MCP token, Claude tokens). `0`: every run shares `AGENT_USER`. Build argument of the same name sets how many accounts the image creates |
| `AGENT_USER` | `agent` in the image | System user the agents' `claude` runs as, through `sudo`. Empty: agents share the backend's user (desktop app, local dev), with a warning at startup |
| `CONTEXT_RESET_EVERY_TASKS` | `5` | Tasks an employee takes part in when they end (merged or cancelled: as assignee, reviewer, QA or security reviewer, or as the one who merged or cancelled it; counted once per task) before their next run starts on a blank context: their Claude sessions are no longer resumed. `0` turns it off. Notes, tasks, room documents and chat are kept, and a run in progress is never cut |
| `CONTEXT_RESET_EVERY_RUNS` | `5` | Runs a single Claude task session (for one employee) serves before the next run on that subject starts a new session instead of resuming it. Conversation wakeups never resume: each starts a new session, as the prompt cache has expired between two wakeups. The employee's other sessions are untouched, and it works next to `CONTEXT_RESET_EVERY_TASKS`. `0` turns it off. A run in progress is never cut |
| `EXTRA_APT_PACKAGES` | | System packages the agents need, e.g. `nodejs npm` (needs a local build) |

The lead and devops can also install Node.js or Go for the whole team on their own, and a shared
Python venv (`install_toolchain python`, with `packages`, e.g. `pytest pytest-asyncio==0.23.0`).
The venv lives in `/data/toolchains/python-venv`, sees the image's packages, and its `python`,
`pip` and commands (`pytest`...) come first in the agents' `PATH`, so `python -m pytest` still works
after a redeployment. Agents only read the toolchains: packages are installed by the server, from
PyPI, and the tool takes plain names with an optional version (no option, URL or path). Call it
again to add packages. Only wheels are installed (no build step runs as the server), the venv is only writable by the server (a venv agents could write in is recreated), and no pip cache is kept. After a base
image upgrade to another Python minor, the venv is recreated by the next `install_toolchain python`.

## Security

- Security review is not self-declared: in the modes with a security gate, a pull request
  that changes a path listed in `backend/app/sensitive_paths.py` (dependency manifests and
  lockfiles, Dockerfiles, entrypoints, sudoers, `runner.py`, `config.py`, `mcp_server/`,
  scripts, secrets and CI files) needs security's approval, whatever the author flags. The
  files come from the pushed branch; the author's flag can only add the gate.
- The GitHub token never reaches the agents: the server pushes, opens pull requests and
  merges for them. Agents only get the environment variables they need, and their own
  Claude token.
- Secrets (`ADMIN_TOKEN`, `GITHUB_TOKEN`, `CLAUDE_CODE_OAUTH_TOKENS`, the database password)
  are Docker secrets, files and not environment variables: the container's environment holds
  none, so the healthcheck and every child process (git, `claude`) start without them. The
  entrypoint closes `/run/secrets` and gives the server a private copy in
  `/run/palabre-secrets` (read by `pydantic-settings`' `secrets_dir`).
- Agents run as another system user. The server runs as `palabre` (uid 1000); each `claude`
  process is started as `agent` (uid 1001) through one `sudo` rule that only allows the
  `claude` binary, so an agent cannot read the server's environment, `/proc/<pid>/environ`,
  database URL or tokens. In `/data`, only the server can read the project's reference
  clone and `runtime/`; agents write in their task and desk clones, Claude's sessions and
  the Go cache, and only read the toolchains. The server's `PATH` never includes the
  toolchains. Do not add `no-new-privileges` to the compose file: `sudo` needs it off.
  Every run is `sudo -n -u agent` with a fixed list of variables (`HOME`, `PATH` with the
  toolchains, `CLAUDE_CONFIG_DIR`, the account's token, git identity, `safe.directory` set to the run's
  own clone), never inherited from the
  server. Secrets travel in that environment, not in the command line, so `ps` does not show
  them; the run's MCP config is a file in `/data/run`, which agents can cross but not list.
  A second `sudo` rule only lets the server kill a process group of the agent, to stop a run
  that timed out. A third one runs `palabre-rm-clone`, a root-owned script that, as `agent`, only
  empties a desk or task clone (files the agent made outside the shared group, which the
  server cannot remove itself; the server then removes the empty directory). With `AGENT_USER` empty, none of this applies.
  Publishing a task branch (`push_task_branch`) fetches it from the agent's clone through `palabre-upload-pack`, a fifth `sudo` rule (root-owned script, an exact task clone path only) that runs `git upload-pack` as the account owning the clone: whatever the agent puts in its `.git` (alternates, `commondir`, symlinks), the OS refuses it another project's objects. The server fails closed, with an explicit error, if the clone is no longer owned by a pool account (taken back) or if `sudo` or the script is missing. The fetch into the reference runs with `transfer.fsckObjects`, so a malformed pack never reaches GitHub, and the indirection denylist stays as defence in depth. In the legacy shared-account mode (no pool), the clones stay palabre's and the upload-pack runs as the shared `agent` account, which only reads what that account can already read.
  Each live run's clone and Go cache (`/data/toolchains/gopath/employee-<id>`) are handed to its account just before it starts, by `palabre-claim-clone` (root-owned, run through a fourth `sudo` rule that only accepts a clone path and an `agentN` or `palabre` account): owner and group become the account and its private group, so no other run can write a hook, a git config or a Go module there for someone else's run to execute (#160). A task clone is therefore writable by one run at a time: once the run's processes are killed (and only then), the clone and the Go cache go back to `palabre` before the account serves another employee, and the server also takes them back at every start. The script walks the tree with `chown -R -h` / `chmod -R`, which never follow a symlink. If the hand-back fails, the account stays out of the pool until restart. The projects root of the three root-owned scripts and of their `sudo` rules is the `PROJECTS_DIR` build argument (default `/data/projects`), written to `/etc/palabre/projects-root.conf` at build; a script refuses everything if that file is missing or the root is empty, `/`, relative or has odd characters, and the build fails on such a value. The build and the entrypoint also require a root strictly under `/data/` that is none of `/data/run`, `/data/runtime`, `/data/claude`, `/data/toolchains` (or below them), since the entrypoint chowns it as root; an explicitly empty runtime `PROJECTS_DIR` is refused too. `check-isolation.sh` reads the same file. The strict validation of the root lives in the build and in the entrypoint; the root scripts only read the configuration they validated. Without a pool (`AGENT_POOL_SIZE=0`, shared `AGENT_USER`) nothing is claimed: at every start the entrypoint instead gives the clones and Go caches to the group `work` (group-writable, setgid), so the one agent account can still write in them and serve them to `palabre-upload-pack` after a restart. Clones are only taken back to `palabre:palabre` go-rwx with a pool.
  Each live run also gets its own account (`agent1..agentN`, `AGENT_POOL_SIZE`), with a private group the server belongs to: the run's MCP config and Claude config dir are readable by that group only, so another run can read neither the environment nor the config of a live run. Runs beyond the pool size wait for a free account.
  Clones are made with `--no-hardlinks`, so they share no object with the reference (whose
  objects stay private). Desks are recloned at every run and fix themselves. A task clone made
  before this fix still holds hard links: once its work is pushed, delete
  `/data/projects/<id>/worktrees/task-<n>` (as the server user) and it is recreated on the
  agent's next start.
  Claude's sessions are not shared: `/data/claude` (`CLAUDE_STORE_DIR`) is the server's own store (mode 700), with one
  directory per employee. Each run gets a throwaway `CLAUDE_CONFIG_DIR` in `/data/run` holding
  only the session it resumes, and the server copies back the sessions it wrote (regular files
  only) and deletes the directory. A `settings.json` or hook an agent writes there dies with
  the run and never reaches another employee's. Sessions of a volume made before this change
  are purged at the first start (agents begin a new session).
  Known limit: all agents share the one `agent` user, so a run can still read another run's
  process (its token, its MCP config path, its `CLAUDE_CONFIG_DIR`): while a run is live, another
  run can write into its session, which is then collected into that employee's store.
  The isolation is between agents and the server, not between agents. Per-run users or `hidepid` on `/proc` would be the next step.
  To check an image, see [Checking the isolation](#checking-the-isolation).
  Agents still share the container's network, so keep Postgres' password strong.
- Each run gets its own random MCP token, held in server memory: it is revoked when the
  run ends, and the `--mcp-config` file holding it is deleted on the first MCP request.
  A token stolen from another run (`ps`, the config file) stops working once that run is
  over. The token is tied to the run and to its task or conversation (the headers must match
  the scope recorded at start), not to one MCP session: `claude` reopens sessions during a
  run, so each `MCP initialize` is only logged by the backend. Residual risk: all runs share the `agent` uid, so while a run is live another run
  can still read its `/proc/<pid>/environ` or the config file in that short window. The
  real fix is one uid per run (or per sensitive role, the lead) or a sandbox per run
  (bubblewrap, user namespace).
- Each agent's tools come from its role. Merge rules are enforced by the server, not by
  the agents' good will.
- The API is protected by `ADMIN_TOKEN`. Keep the server on your local network or a
  private network: Palabre is not meant to be exposed to the internet.

### Checking the isolation

The Compose smoke test in CI runs the agent pool isolation check and
`check-migration.sh` on the image it builds, and fails on any `FAIL`; the log shows each `ok`
line and a final count. The task flow check needs a scratch GitHub repository, so it stays
manual, as does running either script on another image after changing the Dockerfile, the
entrypoint or the runner. Two scripts in `backend/scripts/`:

```sh
# 1. Migration of a volume made before the agent user (needs Docker on the host only; also run by the CI)
backend/scripts/check-migration.sh <image>

# 2. Agent runs and task flow, in a throwaway container with a scratch GitHub repository
#    (the token only needs to push to it: the check opens a PR there and merges it)
printf %s "$GITHUB_TOKEN" > /tmp/github_token
docker run -d --name palabre-check -v palabre-check-data:/data \
  -v /tmp/github_token:/run/secrets/github_token:ro <image> sleep infinity
docker exec -u root -e CHECK_GITHUB_REPO=owner/scratch-repo palabre-check /srv/scripts/check-isolation.sh
docker rm -f palabre-check && docker volume rm palabre-check-data
```

The second script swaps `claude` for a stub while it runs (use a throwaway container, never
one whose orchestrator is running agents), so no Claude account is needed. It checks that a
run is `uid agent` through `sudo -u` with the right `PATH`; that the agent cannot read the
backend's `environ`, the project reference, `/data/runtime` or the secret files; that a run
past its timeout leaves no agent process; that `sudo` has `!use_pty`; and, with
`CHECK_GITHUB_REPO`, the whole task flow (clone, commit by the agent, push from the
reference, PR, merge). Without `CHECK_GITHUB_REPO` the flow is skipped and the exit code is
non-zero. Every line is `ok` or `FAIL`.

## Develop

```sh
docker compose up -d --build                     # server and web app, from backend/ and frontend/
cd frontend && npm install && npm run tauri dev  # desktop app
```

To check the frontend (TypeScript typecheck, then Vite build), run `npm run check` in
`frontend/`. No linter is configured yet.

Roles, company sizes, research angles and personalities are all defined in
[`backend/app/company/catalog.toml`](backend/app/company/catalog.toml).
A role can set an optional `effort` (`low`, `medium`, `high`, `xhigh` or `max`), passed to `claude --effort`; it is `low` for the product owner, designer, scribe and the research angles, and absent (claude's default) elsewhere. An employee with several roles gets the highest, or the default if one of their roles sets none.

The lead normally ships with `merge_release` and `publish_version` (see above). To publish a release by hand instead, move the `[Unreleased]` entries of [`CHANGELOG.md`](CHANGELOG.md) under the new version, then push a version tag (`git tag v0.2.5 && git push origin v0.2.5`):
GitHub Actions builds the server and web images for amd64 and arm64
(`ghcr.io/enzoblain/palabre`, `ghcr.io/enzoblain/palabre-web`) and the desktop app for
every system, attached to the release. A final `notes` job puts the changes back if the builds overwrote the release body, so the notes always read changes, then download text.
