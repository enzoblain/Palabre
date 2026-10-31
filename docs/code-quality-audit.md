# Code quality audit
Scope: backend/app and frontend/src. Naming, language, typing, module size and coupling, hardcoded values. Complements docs/audit/architecture.md (runtime issues are not repeated). No fix in this PR. Effort: S < 1 day, M 1-3 days, L > 3 days.

Language: no non-English comment or identifier in code (accents only in data: catalog names, LANGUAGES native names, fr.ts). One leftover: French room names in projects.py:239 (see L3).

## High
H1. WorkflowError lives in services.py:64 while app/errors.py holds the error codes; every layer imports a domain exception from the conversation service. Fix: move WorkflowError (and NothingToRelease, projects.py:503) to errors.py; re-export from services.py for one release. S.
H2. HTTP status parsed from error strings: github.py:207, :247, :284 test `" 404 " in str(exc)`; _api (:167-168) only puts the status in the message. Fix: GitHubError.status set by _api; callers test exc.status == 404. S.
H3. Stringly typed kinds: Project.kind (~25 literal "company"/"research" comparisons in projects.py, dispatcher.py, merge_watch.py, team.py, api/), Room.kind ("team" literal at services.py:289, projects.py:243 next to DIRECTION/DM constants), Wakeup/AgentRun.kind (events.py:92, dispatcher.py:293/319, retries.py:26), Message.request_kind/request_status (models.py:250-251, plain String although RequestStatus exists). Fix: StrEnum per field (ProjectKind, RoomKind, RunKind, RequestKind) via str_enum, same values, no migration. M.
H4. projects.py (860 lines) does five jobs: creation/teams, channels, startup data fixes (:228-325, :844-860), releases (:454-704), boss requests/decisions (:754-843). Fix: move release helpers (:625-654) into release.py, requests/decisions into requests.py, startup fixes into startup.py called by main.py. M.
H5. Error codes mirrored by hand: frontend/src/api.ts:242-295 repeats ErrorCode. Fix: a backend test comparing api.ts ERROR_CODES with ErrorCode (no codegen, no dependency). S.

## Medium
M1. services.py (678 lines) mixes app settings (:73-115), chat validation (:118), boss requests (:269-420), channels/DMs (:421-556), room document, notes. Fix: app_settings.py, requests.py (with H4); services.py keeps what CLAUDE.md says. M.
M2. `-> dict` on public boundaries: workflow.py:97/:119/:145, services.py:557, projects.py:507/:528/:705/:726, github.py:157 and wrappers (:226, :259, :271, :476, :485, :512), team.py:27/:52/:57, MCP tools. Fix: TypedDict or existing Pydantic schemas for task_summary/task_detail/room_context/release_plan and GitHub payloads. M.
M3. `Any` where the type is known: usage.py:23/:43 (Protocol of AgentRun columns), mcp_server/server.py:19 (SDK Request type); event payload dict read by key across modules (models.py:354, services.py:144, workflow.py:60, prompts.py:48). Fix: Protocol, SDK types, TypedDict per event type. S/M.
M4. Front types outside api.ts: DocumentView.tsx:11-19 (Question, Task, RoomDocument, status: string despite TASK_STATUSES); api.ts kind/request_kind as string (:73, :89, :101), Mode.process Record<string, unknown> (:111). Fix: move to api.ts, unions matching H3. S.
M5. Catalog values duplicated in the front: TeamEditor.tsx:9 MAX_AGENTS (schemas.py:116), :11 MODELS, NewProject.tsx:12 DEFAULT_MODE, Settings.tsx:11 MODE_KEYS. Fix: serve them via /catalog. S.
M6. Tuning values outside config.py: runner.py:114 MCP_TOOL_TIMEOUT "600000", github.py:165 timeout=30, github.py:268 per_page 100 without pagination, services.py:34-35 chat limits, workflow.py:29 MAX_DIFF_CHARS, front POLL_MS (ConversationView.tsx:11, DocumentView.tsx:8). Fix: tool timeout derived from agent_timeout_s and chat limits in config.py + README; others named constants with a why comment; paginate open PRs. S.

## Low
L1. TeamPanel.tsx also exports ProjectMenu (:11). Fix: ProjectMenu.tsx. S.
L2. github.py also runs all local git commands. Fix: say it in the module docstring. S.
L3. One-shot data fixes run at every startup (main.py:56-60), incl. French room names (projects.py:239). Fix: delete once applied everywhere, or move to versioned migrations (architecture H5). S.
L4. New httpx.AsyncClient per GitHub call (github.py:165). Fix: one client opened in the lifespan. S.
L5. Cryptic names: T TypeVar (services.py:45), _SWEEP_ABOVE (api/deps.py:30). Fix: rename or one-line comment. S.
L6. services._app_settings (:86) module-level mutable config. Fix: document with the in-memory state list (architecture M5). S.

## Suggested order
H1, H2, H5, then H3, then H4 + M1 together, then M2-M4, then the rest.
