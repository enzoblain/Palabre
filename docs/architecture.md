# Architecture

```
 Phone / browser ──► :2810  Web app (nginx) ─► :2710  Server (FastAPI) ──── PostgreSQL
                                                  │
                                                  ├── Orchestrator: wakes agents up on events
                                                  ├── claude -p runs, one per agent wake-up
                                                  └── MCP server: the agents' tools
                                                            │
                                                         GitHub
```

- **Server** (`backend/`): Python, FastAPI, SQLAlchemy. It stores the projects, runs the
  orchestrator, clones the repositories and talks to GitHub.
- **Agents**: each wake-up is a `claude -p` run with the employee's system prompt, built
  from the role catalog (`backend/app/company/catalog/`) and, for company projects, the
  repository's `CLAUDE.md` (read by the backend from the reference clone, since runs only
  load the user settings). They act through an MCP
  server whose tools depend on their role: only a lead can merge, only reviewers, QA and
  security can approve a pull request.
- **Apps** (`frontend/`): React and TypeScript, served by nginx for the browser.
- **Shared contract** (`shared/`): the API types and error codes used by both apps, types and constants only (no runtime dependency). See [Mobile app](mobile.md#sharing-code-with-the-web-app).
- **Mobile app** (`mobile/`): Expo (React Native) and TypeScript; talks to the same `/api`. See [Mobile app](mobile.md).
