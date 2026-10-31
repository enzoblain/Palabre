# Design: jobs and personalities inventory

Status: proposal, no application code in this PR. Request from the CEO: turn roles ("jobs") and personalities into an inventory (a marketplace) that gathers everything about an entry (name, description, permissions, tools), lets the custom team screen pick a job and a personality from it, and makes adding one easy.

## 1. Today

Everything lives in `backend/app/company/catalog.toml`, loaded by `team.load_catalog()` (cached, untyped `dict`):

- `[roles.*]` (company) and `[research.roles.*]`: `title`, `model`, optional `effort`, `mission`, `responsibilities`, `forbidden`, `deliverables`, `escalation`, `success`, `permissions`, `wakes_on`. `load_catalog` merges both families into one `roles` namespace and tags each with `kind`.
- `permissions` are bare strings. What they unlock is declared elsewhere, in `mcp_server/permissions.py` (`MCP_TOOLS`: tool -> permissions, `CLAUDE_TOOLS`: permission -> Claude built-ins). A typo in a role's permission is silent. The inventory cannot show "this job can do X" without re-reading that module.
- `[personality]` (and `[research.personality]`) is not a list of personalities but a *generator*: `levels`, `axes` (`key`, `label`, `low`, `high`, `diverse`), a pool of `quirks` (plain strings) and `style` (`verbosity`, `tone` value lists). An employee's personality is `traits` (axis -> level), `quirks`, `style`, drawn at random (`_draw_traits`, `_make_employee`).
- `Employee` (dataclass, stored as JSON in `models.py`) keeps `roles`, `title`, `model`, `permissions` copied at creation; `projects.refresh_permissions` re-syncs permissions from the catalog at startup.
- API (`api/catalog.py`): `/catalog/roles`, `/catalog/personality`, `/catalog/modes`, `/catalog/names`, all `-> dict`, no response model.
- Custom team (`TeamEditor.tsx`, `MemberIn`): roles are chips (title only, no description or permissions shown); the personality is edited axis by axis, quirk by quirk, with a "random" button. There is no notion of picking a ready-made personality.
- Adding a job means editing a 760-line TOML (plus `permissions.py` if it needs a new permission); adding a personality is not possible, only adding axes or quirks to the pool.

Pain points: no schema validation at load, no single description of "what a permission is", nothing reusable as a ready-made personality, the UI cannot present an inventory.

## 2. What changes

Two first-class, typed entry kinds, each with a stable `key`: **Job** and **Personality** (a named, ready-made profile). A third small kind, **Permission**, makes the permission to tools mapping part of the same inventory. Random generation keeps working: it becomes "draw a Personality preset, or draw traits as today" without changing seeds' behaviour for existing teams (see section 7).

### Single source of truth

One directory of TOML files, parsed at startup into frozen Pydantic models (`extra="forbid"`), so a bad entry fails fast with the file name:

```
backend/app/company/catalog/
  jobs/<key>.toml
  personalities/<key>.toml
  permissions.toml
  settings.toml      # modes, channels, names, boss prompts, personality axes/levels/styles (unchanged content)
```

`catalog.toml` is split, not rewritten: role blocks become `jobs/*.toml`, modes and the rest go to `settings.toml`. `load_catalog()` stays as a thin facade for one release so callers migrate gradually.

### Job

| Field | Type | Notes |
|---|---|---|
| `key` | `str` (slug, = file name) | unique across kinds, as today |
| `kind` | `Literal["company", "research"]` | replaces the merge of two sections |
| `title` | `str` | |
| `description` | `str` | one or two lines for the inventory card (new) |
| `model` | `Literal["haiku", "sonnet", "opus"]` | default model |
| `effort` | `Literal["low","medium","high","xhigh","max"] \| None` | |
| `mission`, `escalation`, `success` | `str` | prompt text, as today |
| `responsibilities`, `forbidden`, `deliverables` | `list[str]` | as today |
| `permissions` | `list[PermissionKey]` | validated against `permissions.toml` |
| `wakes_on` | `list[WakeEvent]` | validated against the event names in `orchestrator/events.py` |
| `tags` | `list[str]` | optional, for filtering ("dev", "review", "ops") |

### Permission

`permissions.toml`: `key`, `label`, `description`, `mcp_tools: list[str]`, `claude_tools: list[str]`. This replaces `MCP_TOOLS` and `CLAUDE_TOOLS` in `mcp_server/permissions.py`, which keep their functions (`mcp_tools_for`, `claude_tools_for`) but read the inventory. The `research` permission keeps its dynamic `DRAFTS_GLOB` through a placeholder resolved in code. A test checks that every MCP tool registered in `tools.py` appears in exactly one permission, keeping the rule "a new tool must be listed there". This file is sensitive (it gates the agents' tools): reviewed by security like `catalog.toml` today.

### Personality

A ready-made profile, which is what the user picks:

| Field | Type | Notes |
|---|---|---|
| `key` | `str` | file name |
| `kind` | `Literal["company", "research"]` | axes differ per kind |
| `label` | `str` | e.g. "The cautious architect" |
| `description` | `str` | inventory card text |
| `traits` | `dict[AxisKey, Literal[-2,-1,0,1,2]]` | keys validated against the kind's axes |
| `quirks` | `list[str]` (max 5, each <= 200) | same limits as `MemberIn` |
| `style` | `dict[str, str]` | each value validated against the allowed `style` values |

The generator parameters (axes, levels, quirk pool, style values) stay in `settings.toml`, since they define the vocabulary a Personality is written in and what a "random" draw uses. Presets can be seeded from the existing pool (a handful of archetypes), and the UI keeps the free editing of axes and quirks on top of a chosen preset.

Employee storage does not change: `Employee` still stores the resolved `traits`/`quirks`/`style`, so a later edit of the inventory never rewrites a running team's personality (permissions still refresh as today). Optionally `personality_key: str | None` is recorded for display only.

## 3. Adding an entry

From a file, no code change:

1. Copy a similar file in `catalog/jobs/` or `catalog/personalities/` and rename it to the new key.
2. Fill in the fields (the schema lists them; an unknown field or permission is rejected).
3. For a job needing a new capability, add it to `permissions.toml` (with the MCP tools it unlocks).
4. Run `python -m pytest` (a catalog test loads every file and checks cross references) and restart the backend: the entry shows in the inventory.

From the UI: out of scope for the first iteration. It is a good second step, and the design allows it: user-created entries would be saved as TOML (or a DB table `catalog_entry` with the same Pydantic model) in a `custom/` layer overriding nothing, and flagged `builtin: false` in the API. Recommendation: ship file-based first (cheap, reviewed in git, keeps permissions under code review), then decide on UI creation, with security input, since a job's permissions grant tools.

## 4. API for the front

Typed with response models in `api/schemas.py`; read-only, same `kind` query parameter as today.

- `GET /catalog/jobs?kind=` -> `list[JobOut]` (all fields above, plus `permissions` expanded to `{key, label, mcp_tools, claude_tools}`, so the card can show "what this job can do").
- `GET /catalog/jobs/{key}` -> `JobOut`, 404 `CATALOG_ENTRY_NOT_FOUND`.
- `GET /catalog/personalities?kind=` -> `list[PersonalityOut]`.
- `GET /catalog/personalities/{key}`.
- `GET /catalog/permissions` -> `list[PermissionOut]`.
- `GET /catalog/personality` stays (axes, levels, quirks, style) for the editor; `GET /catalog/roles` stays as an alias of `/catalog/jobs` in the old dict shape for one release (backward compatibility for the current front and any client).
- `MemberIn` gains `personality: str | None` (preset key). Order of precedence: explicit `traits`/`quirks`/`style` > preset > random draw, which keeps every current payload valid. Unknown key -> 422 with a clear error code.

## 5. Front

The custom team screen replaces the role chips with a job picker (cards: title, description, model, permission labels, filter by tag; multi-select kept since an employee can combine roles), and adds a personality picker (cards with the traits summary, "random" as the first option, "customise" opening the existing axis/quirk editor). Types come from `api.ts` (no `any`); the hardcoded `MODELS` list moves to the catalog payload (audit M5).

## 6. Task breakdown

Back (B), front (F), with dependencies:

- B1. Typed catalog loader: Pydantic models, split of `catalog.toml` into the directory layout, `load_catalog()` facade, load-time validation, tests. No behaviour change, existing tests must pass untouched. Sensitive.
- B2. Permissions inventory: `permissions.toml`, `mcp_server/permissions.py` reads it, test "every MCP tool is covered once". Depends on B1. Sensitive.
- B3. Personality presets: model, a first set of preset files, `personality` field on `MemberIn`, resolution in `custom_employee`. Depends on B1.
- B4. Inventory API: the endpoints of section 4 with response models, `/catalog/roles` kept compatible. Depends on B1, B2, B3.
- B5. README section "Add a job or a personality" and `CLAUDE.md` module map update. Depends on B4.
- F1. Types and client in `api.ts` for the new endpoints. Depends on B4.
- F2. Job picker in `TeamEditor`. Depends on F1.
- F3. Personality picker in `TeamEditor` (preset, random, customise), i18n strings. Depends on F1; can run in parallel with F2.
- Later, separate decision: B6/F4 creation of entries from the UI.

B1 is the only risky step (everything reads the catalog); keeping the facade lets B2 and B3 land independently.

## 7. Risks and compatibility

- Seeded generation: `generate_team(mode, seed)` must stay deterministic for stored teams. B1 keeps the order of keys and the `rng` call sequence; a test pins the output of a few known seeds before and after the split.
- Existing projects store resolved employees, so they are unaffected; `refresh_permissions` keeps working through the facade.
- API: old endpoints and shapes are kept for at least one release.
- Files under `company/catalog/` and `permissions` are sensitive paths: `sensitive_paths.py` must list the new locations (B1/B2), otherwise the security gate would silently stop applying.
- Uncertainty: whether the marketplace wording means sharing entries across installs (import/export). Not covered here; the one-file-per-entry layout would make it a simple copy.
