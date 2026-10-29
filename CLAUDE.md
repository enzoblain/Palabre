# CLAUDE.md

Palabre is a company of AI agents that works for its CEO (the user): a lead splits work into tasks, developers open pull requests, reviewers and QA check them. Agents are `claude -p` runs that act through an MCP server. See the [README](README.md#how-it-works) for the product and [Architecture](README.md#architecture) for the big picture; this file only maps the code.

## Stack

- Backend (`backend/`): Python 3.12+, FastAPI, SQLAlchemy async on PostgreSQL, the `mcp` SDK, httpx.
- Frontend (`frontend/`): React + TypeScript + Vite, packaged for desktop with Tauri (`src-tauri/`) and served by nginx for the browser.

## Module map

Backend, in `backend/app/`:

- `main.py`: FastAPI app, startup, mounts the API, the MCP server and the scheduler.
- `config.py`: settings from environment variables (see [Configuration](README.md#configuration)).
- `db.py`, `models.py`: engine/session and SQLAlchemy models.
- `api/`: REST routers for the apps (projects, rooms, conversations, tasks, settings, catalog, monitoring); `schemas.py` holds the Pydantic models.
- `services.py`: conversations, room document, notes and events, shared by the API and the MCP server.
- `workflow.py`: task lifecycle (creation, assignment, review, merge) and the merge gates of each company size.
- `github.py`: git and GitHub operations. Only the backend runs them; agents never get the token.
- `release.py`: SemVer next version, version files and CHANGELOG entry (pure functions); `projects.prepare_release` commits them on the team's branch.
- `worktrees.py`: local clone of each project and one clone per task and per desk.
- `projects.py`, `company/team.py`: project creation and random team generation from the catalog.
- `company/catalog.toml`: roles, company sizes, research angles, personalities and role permissions.
- `runner.py`: launches one agent run (`claude -p`) on the employee's Claude account; `accounts.py` picks the account.
- `toolchains.py`: toolchains agents install for the whole team, without root.
- `orchestrator/`: turns events into wakeups (`events.py`), runs them (`dispatcher.py`), builds agent prompts (`prompts.py`), and handles rituals, retries and research phases (`scheduler.py`, `retries.py`, `research.py`).
- `mcp_server/`: the agents' tools (`tools.py`), which role gets which (`permissions.py`), request auth (`auth.py`), server setup (`server.py`).

Frontend (`frontend/`): `src/` (`api.ts` backend client, `router.ts`, `components/`), `src-tauri/` for the desktop shell.

## Run and check

How to run the app: see [Develop](README.md#develop). Checks:

```sh
cd backend && python -m pytest   # backend tests, fixtures in the README's Tests section
cd frontend && npm run check     # front check
```

Details: [Tests](README.md#tests).

## Conventions

- Everything in the repo (code, comments, docs) is in English. So is everything that goes to GitHub (commit messages, PR titles and descriptions, review comments, release notes). Commits and PR titles use Conventional Commits (`feat(scope): ...`); release notes list the changes grouped by type, then keep the standard text of `release.yml`; see [How it works](README.md#how-it-works). Versions follow Semantic Versioning 2.0.0, computed from the Conventional Commits since the last `vX.Y.Z` tag (`fix`/`perf` patch, `feat` minor, `!` or `BREAKING CHANGE` major, minor while in 0.x); see [How it works](README.md#how-it-works). The chat and tasks stay in the team's language.
- Each backend module starts with a one-line docstring saying what it is for; keep that style, and comments short and about the why.
- Async everywhere on the backend; no blocking calls in request or orchestrator paths.
- Permissions live in the catalog and `mcp_server/permissions.py`: a new MCP tool must be listed there.
- Keep dependencies minimal; avoid adding one for something the stdlib does.
- Do not duplicate the README: link to it and update it when behavior changes.
