# Catalog of jobs and personalities: design

Goal (from the boss): one inventory that holds every job and every personality (name, description, permissions, tools), where the custom team editor picks from, and where adding an entry is easy. No application code in this PR; tasks at the end. Follows decision #44 (layout and model) and #45 (sensitive paths).

## Today
- `backend/app/company/catalog.toml` (760 lines) holds everything: boss prompts, roles (company and research), channels, modes, personality axes, quirks, styles, first names. `team.load_catalog()` returns an untyped dict; research roles/modes are merged in with `kind = "research"`.
- A role = title, model, effort, mission, responsibilities, forbidden, deliverables, escalation, success, permissions, wakes_on. No short description: the UI shows `mission` as a tooltip.
- `mcp_server/permissions.py` maps a permission to MCP tools (`MCP_TOOLS`) and Claude tools (`CLAUDE_TOOLS`). The tools a role gets are never shown to the boss.
- A "personality" is not an entry: it is drawn per employee (a level -2..2 per axis, 1-2 quirks, a style). There is nothing to pick, only sliders and checkboxes (`TeamEditor.tsx`).
- API: `GET /catalog/roles`, `/catalog/personality`, `/catalog/modes`, `/catalog/names` return raw catalog dicts (`-> dict`). Front types are hand-written in `api.ts`; `TeamEditor.tsx` hardcodes `MODELS` and `MAX_AGENTS`.
- Validation is scattered: `_check_team` (`api/projects.py`), `projects.validate_personality`, `refresh_permissions` at startup. A typo in a permission or a `wakes_on` event in the TOML fails silently.
- Some role keys carry behavior in code: `lead` (merge, direction, `LEAD_REQUIRED`), `reviewer`/`qa`/`security` (merge gates in `workflow.py`), `DEV_ROLES` and `VERSION_ROLES` (`prompts.py`), `rapporteur` (`team.py`).

## What changes
1. One file per entry. Jobs and personality presets move to `backend/app/company/catalog/`:
   - `catalog/company/roles/<key>.toml`, `catalog/research/roles/<key>.toml`
   - `catalog/company/personalities/<key>.toml`, `catalog/research/personalities/<key>.toml`
   - `catalog.toml` keeps the shared parts: boss, channels, modes, axes, quirk pool, styles, names.

   The key is the file name, the kind is the folder. Adding an entry = adding a file, no merge conflict in one big file.
2. A typed model is the single source of truth: `company/catalog.py` loads and validates every file with Pydantic (already a dependency) at startup and in a test. An invalid entry stops the backend with the file name and the field. `team.py`, `api/` and `events.py` read typed objects, not dicts.
3. Personality presets: named personalities the boss can pick (e.g. "Pragmatic", "Perfectionist", "Challenger"), then tweak. Random draw stays the default.
4. The API serves the inventory with descriptions and the resolved tools of each job, and the custom editor picks from it.
5. Code keeps using the word "role" (`Employee.roles`, permissions, events); "job"/"métier" is UI wording only. Renaming would touch every module for no gain.

## Data model
Pydantic, `extra="forbid"`, frozen.

Role (job):
- `key`: str (file name, `^[a-z][a-z0-9_]*$`), `kind`: `Literal["company", "research"]` (folder)
- `title`: str, `description`: str (new: one or two sentences for the inventory card)
- `model`: `Literal["haiku", "sonnet", "opus"]`, `effort`: `Literal["low", "medium", "high", "xhigh", "max"] | None`
- `mission`: str, `responsibilities`: list[str] (min 1), `forbidden`: list[str], `deliverables`: list[str], `escalation`: str, `success`: str
- `permissions`: list[Permission], `wakes_on`: list[EventType]
- `category`: `Literal["management", "engineering", "quality", "product", "support", "research"]` (groups the inventory)

`Permission` is a `Literal` built from the keys used in `permissions.py` (`MCP_TOOLS` values and `CLAUDE_TOOLS` keys). `permissions.py` stays the source: there is no `permissions.toml`, and a test checks the `Literal` and the module stay in sync. `EventType` is a `Literal` of the events that can wake someone (one constant in `orchestrator/events.py`, which also removes the `TASK_EVENTS` duplicate, audit L1).

PersonalityPreset:
- `key`: str, `kind`: `Literal["company", "research"]`
- `label`: str, `description`: str
- `traits`: `dict[str, Level]` where `Level = Literal[-2, -1, 0, 1, 2]` and every key is an axis of that kind (missing axis = 0)
- `quirks`: list[str] (0 to 5, max 200 chars each, free text allowed like in the editor today)
- `style`: `{verbosity, tone}` with values from the kind's style lists

Cross-checks at load: modes' seats and channels only use existing role keys; presets only use existing axes and styles. Employee rows do not change (they keep the resolved roles, traits, quirks, style): no migration.

## Team constraints
Rules the loader and the custom team validation enforce, because code reads them by key or by permission:

- `merge` and `code` are never combined. The backend refuses to start if a role declares both. The check also runs on the union of the permissions of each seat when the modes are loaded. In `_check_team`, a custom team where one employee cumulates `merge` and `code` (union of their roles' permissions) gets a 422.
- A custom team has exactly one carrier of `ship_release` and exactly one of `manage_channels` (422 otherwise).
- The loader refuses to start if the same key exists in `company` and in `research`. This replaces the silent `|=` merge in `team.py`; the merge gates are read by key, so a shadowing key would silently change who can approve.
- The keys that carry a gate (`lead`, `reviewer`, `qa`, `security`) live in one constant, `GATED_ROLE_KEYS`, read by `workflow.py` instead of literals.
- Any PR touching `catalog/*/roles/` or `permissions.py` is sensitive (decision #45): `sensitive_paths.py` matches these by path, so the security gate applies without anyone having to flag the PR.

## Adding a job
1. Copy an existing file, e.g. `catalog/company/roles/qa.toml`, to `catalog/company/roles/<key>.toml`.
2. Fill in the fields; pick permissions from `permissions.py` (a new tool or capability is a code change there, reviewed by security).
3. Optional: add it to a mode's seats or a channel in `catalog.toml`.
4. Run `cd backend && python -m pytest tests/test_catalog.py`, then restart the backend (`refresh_permissions` applies the change to existing teams).

Limit: a new job gets no gate behavior (merge approval, lead duties) unless code reads its key; the README says which keys are special.

## Adding a personality
1. Copy `catalog/company/personalities/<any>.toml` to `<key>.toml`.
2. Set label, description, the levels of the axes you care about, quirks and style.
3. Run the catalog test, restart.

No creation from the UI in this version: jobs carry permissions (security-sensitive, they must go through review), and keeping one source in the repo avoids a second store to sync. Presets created from the UI (a DB table, no permissions at stake) can come later if the boss asks.

## API
All under `/api/catalog`, typed response models in `schemas.py`, mirrored in `api.ts`.
- `GET /catalog/roles?kind=` -> `dict[str, RoleOut]`: the role fields + `tools: {mcp: list[str], claude: list[str]}` computed with `mcp_tools_for` / `claude_tools_for`. Same path and dict shape as today, only fields added: the front keeps working.
- `GET /catalog/personalities?kind=` -> `dict[str, PersonalityPresetOut]`.
- `GET /catalog/personality?kind=` (axes, levels, quirk pool, styles): unchanged.
- `GET /catalog/limits` -> `{models: list[str], max_agents: int}`: removes `MODELS` and `MAX_AGENTS` from `TeamEditor.tsx` (audit M5).
- `MemberIn` gets `personality: str | None` (a preset key of the project's kind). `custom_employee` applies the preset, then the explicit traits/quirks/style override it, then what is still missing is drawn. Unknown key -> 422 `UNKNOWN_PERSONALITY` (new `ErrorCode`, added to `api.ts` too).

## Risks and compatibility
- Seeded generation: `generate_team(mode, seed)` must stay deterministic for stored teams. A test pins the output of a few known seeds before the split, and B1 keeps the order of keys and the `rng` call sequence so it passes unchanged.
- Sensitive paths: `sensitive_paths.py` matches by path (`catalog/*/roles/`, `permissions.py`), not by a list of file names, so adding a job file cannot silently skip the security gate.
- Façades: if `load_catalog()` or `/catalog/roles` keep an old shape for callers, they get a removal date or a ticket in B1 (no open-ended compatibility layer). The `/catalog/roles` path itself stays, with fields added only.
- Existing projects store resolved employees, so they are unaffected; `refresh_permissions` keeps working.
- Uncertainty: whether the "marketplace" wording means sharing entries across installs (import/export). Not covered here; one file per entry would make it a simple copy.

## Tasks
Back (Malik / Mehdi):
- B1. Split `catalog.toml` into per-entry files, add `company/catalog.py` (Pydantic models, loader, cross-checks), switch `team.py` and `api/catalog.py` to it, `Permission`/`EventType` constants and their sync test, `tests/test_catalog.py`. No behavior change; add `description` and `category` to every role. Includes the Team constraints above (load-time checks, `GATED_ROLE_KEYS`, the `_check_team` 422s, no duplicate key across kinds), the seed-pinning test and the path-based `sensitive_paths.py`. `CLAUDE.md` module map + README "Adding a job". No dependency.
- B2 (after B1). Personality presets: model, 4-6 presets per kind, `MemberIn.personality`, `custom_employee`, `UNKNOWN_PERSONALITY`, tests, README "Adding a personality".
- B3 (after B1). API: `RoleOut` with tools, `PersonalityPresetOut`, `/catalog/limits`, response models instead of `-> dict`, tests. Can run in parallel with B2; `/catalog/personalities` lands with B2.

Design (Emma):
- D1. Inventory mockup (job cards by category with description, model and tools; personality cards), and how it fits in the custom team editor.

Front (Salomé):
- F1 (after B3, D1). `api.ts` types; job picker in `TeamEditor` from the inventory (cards instead of bare chips, tools shown), `MODELS`/`MAX_AGENTS` from `/catalog/limits`.
- F2 (after B2, F1). Personality preset picker in `TeamEditor`: pick a preset, sliders/quirks prefilled and still editable; "random" kept.

Security (Inès) reviews B1 and B3 (permissions and tools exposure).
