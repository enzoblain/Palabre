# CLAUDE.md

Palabre is a company of AI agents that works for its CEO (the user): a lead splits work into tasks, developers open pull requests, reviewers and QA check them. Agents are `claude -p` runs that act through an MCP server. See the [README](README.md#how-it-works) for the product and [Architecture](README.md#architecture) for the big picture; this file only maps the code.

## Stack

- Backend (`backend/`): Python 3.12+, FastAPI, SQLAlchemy async on PostgreSQL, the `mcp` SDK, httpx.
- Frontend (`frontend/`): React + TypeScript + Vite, packaged for desktop with Tauri (`src-tauri/`) and served by nginx for the browser.

## Module map (`backend/app/`)

- `main.py`: FastAPI app, startup, mounts the API, the MCP server and the scheduler.
- `config.py`: settings from environment variables (see [Configuration](README.md#configuration)).
- `db.py`, `models.py`: engine/session and SQLAlchemy models.
- `api/`: REST routers for the apps (projects, rooms, conversations, tasks, settings, catalog, monitoring); `schemas.py` holds the Pydantic models.
- `services.py`: conversations, room document, notes and events, shared by the API and the MCP server.
- `workflow.py`: task lifecycle (creation, assignment, review, merge) and the merge gates of each company size.
- `github.py`: git and GitHub operations. Only the backend runs them; agents never get the token.
- `worktrees.py`: local clone of each project and one git worktree per task.
- `projects.py`, `company/team.py`: project creation and random team generation from the catalog.
- `company/catalog.toml`: roles, company sizes, research angles, personalities and role permissions.
- `runner.py`: launches one agent run (`claude -p`) on the employee's Claude account; `accounts.py` picks the account.
- `toolchains.py`: toolchains agents install for the whole team, without root.
- `orchestrator/`: turns events into wakeups (`events.py`), runs them (`dispatcher.py`), builds agent prompts (`prompts.py`), and handles rituals, retries and research phases (`scheduler.py`, `retries.py`, `research.py`).
- `mcp_server/`: the agents' tools (`tools.py`), which role gets which (`permissions.py`), request auth (`auth.py`), server setup (`server.py`).

Frontend: `frontend/src/` (`api.ts` backend client, `router.ts`, `components/`), `frontend/src-tauri/` for the desktop shell.

## Run and check

```sh
docker compose up -d --build                     # server (:2710) and web app (:2810)
cd frontend && npm install && npm run tauri dev  # desktop app
cd frontend && npm run build                     # front check: tsc --noEmit, then vite build
```

There is no backend test suite yet. To check backend changes, run the stack with docker compose (PostgreSQL included) and hit `/health`, or at least `python -m compileall backend/app`. If you add tests, say how to run them here.

## Conventions

- Everything in the repo (code, comments, docs, commit messages) is in English.
- Each backend module starts with a one-line docstring saying what it is for; keep that style, and comments short and about the why.
- Async everywhere on the backend; no blocking calls in request or orchestrator paths.
- Permissions live in the catalog and `mcp_server/permissions.py`: a new MCP tool must be listed there.
- Keep dependencies minimal; avoid adding one for something the stdlib does.
- Do not duplicate the README: link to it and update it when behavior changes.
