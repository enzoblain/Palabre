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

You post what you want in `#general`. From there the team works on its own:

1. **The lead** splits the work into tasks with acceptance criteria and assigns them.
2. **A developer** works on the task in its own git branch and worktree, then opens a pull request.
3. **Reviewers, QA and security** read the diff and approve or request changes, as the
   company's rules require.
4. **The lead** merges once every rule is met. Nothing reaches the project's branch otherwise.

Along the way the team holds a daily stand-up, records decisions in each room's shared
document, and asks you when something is yours to decide. Decisions and questions waiting
for you land in your inbox.

A new project works on a `dev` branch, created from the repository's default branch if
missing (an empty repository gets `main` then `dev` from its first commit), and every
task's pull request targets it. Only a release reaches production. To switch an existing
project, point it at `dev` in the settings, or ask the lead to run `set_working_branch`
(`dev`); open pull requests are retargeted. When a step is ready, the lead opens the pull
request from `dev` to `main` and you get it in your inbox: one click merges it, or reject
it to close it. The lead never merges into the repository's default branch: that one is yours.

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

To publish a release, push a version tag (`git tag v0.1.0 && git push origin v0.1.0`):
GitHub Actions builds the server and web images for amd64 and arm64
(`ghcr.io/enzoblain/palabre`, `ghcr.io/enzoblain/palabre-web`) and the desktop app for
every system, attached to the release.
