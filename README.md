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
| Multinational | 16 | Two approvals, QA, security, CI, a changelog, and your validation of every decision |

You only talk to the lead, in `#direction`: it is the one channel you can write in, and
it holds only you and the lead. The team works in its own channels (`#general`,
`#engineering`...) and the lead can open more (`create_channel`: `#backend`, `#front`...).
You read every channel live but they are read-only for you (the API refuses your messages
there), and only the lead is woken by what you post. The lead relays between direction and
the team. Existing projects get their `#direction` channel at startup; their rooms become
team channels.

From there the team works on its own:

1. **The lead** splits the work into tasks with acceptance criteria and assigns them.
2. **A developer** works on the task in its own git worktree, then opens a pull request. The branch starts as `task/<id>` and, at the first
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
team's first channel. Green means `merge_release`, then `publish_version`.

A task stuck in review does not wait for someone to notice: if its PR conflicts with the team's
branch, if no CI check is reported `CI_MISSING_MINUTES` (10 by default) after the submission, or if
the CI is red on an otherwise approved task, the task goes back to its dev (`changes_requested`)
with the problem (rebase, missing CI, failing checks) and a "Palabre" line is posted in the team's
first channel. The dev is woken up once per head SHA. A red CI only sends the task back once it is
otherwise approved (no other merge rule is missing); before that, reviewers go first.

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
closes its PR if still open and deletes its branch (`task/<id>...` or `<type>/<id>-<slug>`, on GitHub and locally) and its
worktree. Only branches recorded on tasks are touched, never the default branch, `dev` or a
release PR. To clean the backlog, call `POST /api/tasks/cleanup` (admin token): it is idempotent
and GitHub errors (404...) are only logged.

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
missing (an empty repository gets `main` then `dev` from its first commit), and every
task's pull request targets it. Only a release reaches production. To switch an existing
project, point it at `dev` in the settings, or ask the lead to run `set_working_branch`
(`dev`); open pull requests are retargeted. When a step is ready, the lead opens the pull
request from `dev` to `main` and asks you in direction: Validate merges it, Reject closes
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
already exists, or a version that differs from `frontend/package.json`, `tauri.conf.json` or
`Cargo.toml` (bump them first). Both tools are the lead's only (`ship_release` permission in
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
| `ADMIN_TOKEN` | Protects the API; the apps ask for it. E.g. `openssl rand -hex 32` |
| `CLAUDE_CODE_OAUTH_TOKENS` | Run `claude setup-token`. Several accounts: separate their tokens with `\|` |
| `GITHUB_TOKEN` | Fine-grained token on your repositories: Contents and Pull requests (read/write), Checks and Metadata (read) |
| `POSTGRES_PASSWORD` | Letters, digits, `-` and `_` |

The server listens on port `2710` and the web app on port `2810`.

### Updates

```sh
docker compose pull && docker compose up -d
```

Or let Palabre update itself: with `COMPOSE_PROFILES=autoupdate` in `.env`, an `updater`
container checks for a new version every 5 minutes and restarts the server and web app
when one is out. Running agents get 60 seconds to stop cleanly.

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
minute. An account that fails returns an `error` without affecting the others. Tokens from
`claude setup-token` lack the `user:profile` scope and are refused (403): the error says so.
Setting `QUOTA_PROBE_ENABLED=true` makes the backend fall back, for those accounts, to a
1-token message (`QUOTA_PROBE_MODEL`) whose rate-limit headers carry the figures. It is off by
default because it uses the subscription token outside Claude Code and spends a little quota
(and can start a 5-hour window on an idle account).
`GET /settings/usage` is different: it only sums tokens and cost of the runs Palabre made.

## Tests

Backend tests (pytest, no database or network needed):

```sh
cd backend && pip install --require-hashes -r requirements-dev.txt && python -m pytest
```

`tests/conftest.py` holds the shared fixtures: `FakeSession` (in-memory stand-in for
`AsyncSession`), object builders (`make_task`, `make_employee`...), `process` (sets the mode's
merge gates) and `fake_github` (replaces the GitHub and git calls).

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
| `PALABRE_VERSION` | `latest` | Pins a version, e.g. `0.1.7` |
| `PALABRE_PORT` / `PALABRE_WEB_PORT` | `2710` / `2810` | Ports of the server and web app |
| `COMPOSE_PROFILES` | | `autoupdate` turns automatic updates on |
| `PALABRE_UPDATE_INTERVAL` | `300` | Seconds between update checks |
| `TZ` | `UTC` | Time zone, e.g. `Europe/Paris` |
| `DAILY_TIME` | `09:30` | Time of the daily stand-up (weekdays); empty to turn it off |
| `MERGE_REMINDER_MINUTES` | `10` | Minutes a mergeable task waits before the lead is reminded (once) |
| `MAX_CONCURRENT_AGENTS` | `3` | Agents running at the same time, per Claude account |
| `EXTRA_APT_PACKAGES` | | System packages the agents need, e.g. `nodejs npm` (needs a local build) |

The lead and devops can also install Node.js or Go for the whole team on their own.

## Security

- The GitHub token never reaches the agents: the server pushes, opens pull requests and
  merges for them. Agents only get the environment variables they need, and their own
  Claude token.
- Each agent's tools come from its role. Merge rules are enforced by the server, not by
  the agents' good will.
- The API is protected by `ADMIN_TOKEN`. Keep the server on your local network or a
  private network: Palabre is not meant to be exposed to the internet.

## Develop

```sh
docker compose up -d --build                     # server and web app, from backend/ and frontend/
cd frontend && npm install && npm run tauri dev  # desktop app
```

To check the frontend (TypeScript typecheck, then Vite build), run `npm run check` in
`frontend/`. No linter is configured yet.

Roles, company sizes, research angles and personalities are all defined in
[`backend/app/company/catalog.toml`](backend/app/company/catalog.toml).

The lead normally ships with `merge_release` and `publish_version` (see above). To publish a release by hand instead, move the `[Unreleased]` entries of [`CHANGELOG.md`](CHANGELOG.md) under the new version, then push a version tag (`git tag v0.2.5 && git push origin v0.2.5`):
GitHub Actions builds the server and web images for amd64 and arm64
(`ghcr.io/enzoblain/palabre`, `ghcr.io/enzoblain/palabre-web`) and the desktop app for
every system, attached to the release. A final `notes` job puts the changes back if the builds overwrote the release body, so the notes always read changes, then download text.
