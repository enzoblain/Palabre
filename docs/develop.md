# Develop

```sh
docker compose up -d --build                     # server and web app, from backend/ and frontend/
cd frontend && npm install && npm run dev        # Vite dev server on localhost:1420
```

To check the frontend (TypeScript typecheck, then Vite build), run `npm run check` in
`frontend/`. No linter is configured yet.

**Documentation rule.** A PR that changes a behavior, a config variable, a command or an MCP tool documented in `docs/` updates the right file of `docs/` in the same PR; the README stays short. Developers are told so in their prompt, and the Reviewer blocks (`changes`) a PR that does not; QA reports it as a bug.

Roles live in [`backend/app/company/catalog/`](../backend/app/company/catalog), one TOML file per role
(`company/roles/<key>.toml`, the key is the file name). The personality the employees draw from (axes, quirks, styles) is
`company/personality_pool.toml`. Company sizes, channels and first names are in
[`backend/app/company/catalog.toml`](../backend/app/company/catalog.toml). The backend validates every
file at startup and refuses to start, naming the file and the field, if one is invalid.

**Adding a job.** Copy an existing file (e.g. `catalog/company/roles/qa.toml`) to
`catalog/company/roles/<key>.toml`, fill in the fields (permissions come from
`backend/app/mcp_server/permissions.py`; `order` sets the position in lists), optionally add the key to a
mode's seats or a channel in `catalog.toml`, then run `python -m pytest tests/test_catalog.py` and restart
the backend (existing teams get the new permissions). A new job gets no gate behavior: the keys `lead`,
`reviewer`, `qa` and `security` are read by the workflow (`GATED_ROLE_KEYS`). Rules enforced at load: no
role or seat combines `merge` and `code`. A custom team gets a 422
`invalid_team_permissions` when one employee combines `merge` and `code`, or when it does not have exactly
one carrier of `ship_release` and one of `manage_channels`. Role files are sensitive paths: the security
gate applies to them automatically.
**Adding a personality.** Personality presets are named personalities the boss can pick, then tweak (random draw stays the default). Copy a file (e.g. `catalog/company/personalities/pragmatic.toml`) to `catalog/company/personalities/<key>.toml`, set `label`, `description`, `order`, the levels (-2 to 2) of the axes you care about under `[traits]` (an axis left out is neutral), up to 5 `quirks` and the `[style]`. Axes and style values must exist in `personality_pool.toml`: the backend refuses to start otherwise, naming the file and the field. `GET /api/catalog/personalities` lists them. In a hand-made team, a member's `personality` (a preset key) is applied first, then its explicit `traits`, `quirks` and `style` override it; an unknown key gets a 422 `unknown_personality`.

**Creation modes (companies).** `POST /api/projects` takes an optional `creation_mode`. `manual`: the team is the `employees` list (role and personality per member) and has at least 4 members (the lead included; the composition is free, only the count is checked; below, 422 `team_too_small`, like `auto`) and must hold the mandatory member, the `lead`: without one, 422 `lead_required`. `auto`: `description` and `employee_count` (at least 4, the mandatory member included, at most the catalog's team size; below, 422 `team_too_small`), and no `employees` list; the roles are chosen in a later step, so for now the team is still drawn for the mode. `GET /api/catalog/roles/{role}/random-personality` returns a valid random `traits`, `quirks` and `style` for a role (the "random" button; nothing is saved; unknown role: 404 `role_not_found`).

**Editing and deleting projects.** `PATCH /api/projects/{id}` renames the project (`name` is required, not blank, at most 200 characters); the description (AI-generated) and the repository cannot be edited. `DELETE /api/projects/{id}` removes the project from Palabre: its running agent runs are stopped, then its data (rooms, messages, tasks, notes...) and its files on disk (clone, task clones, desks, Claude sessions) are deleted. `POST /api/projects/delete` with `{"ids": [...]}` does the same for several projects, and deletes nothing if one id is unknown (that check is the only all-or-nothing part: the projects are then deleted one by one, each committed on its own). The GitHub repository is never deleted. An unknown project is 404 `project_not_found`.

**Extended jobs.** `catalog/company/extended_roles.toml` indexes the extended jobs (English name, unique key, one of 20 categories, `archetype`; a name in several categories keeps the first). The archetype is a base company role (`lead`, `architect`, `product_owner`, `dev_backend`, `dev_frontend`, `reviewer`, `qa`, `scribe`, `devops`, `security`, `designer`): a role file with an `archetype` can leave out `permissions`, `wakes_on`, `model` and `effort`, which it takes from it, and it acts as that role in the merge gates and event targeting (`held_role_keys`). Extended jobs are only picked in a custom team: a mode's seats refuse them, so the random draw never uses them. The loader checks that each index line has a known category and a base archetype, and that a role file agrees with its line.

A role can set an optional `effort` (`low`, `medium`, `high`, `xhigh` or `max`), passed to `claude --effort`; it is `low` for the product owner, designer and scribe, and absent (claude's default) elsewhere. An employee with several roles gets the highest, or the default if one of their roles sets none.

The lead normally ships with `merge_release` and `publish_version` (see [How it works](how-it-works.md)). To publish a release by hand instead, move the `[Unreleased]` entries of [`CHANGELOG.md`](../CHANGELOG.md) under the new version, then push a version tag (`git tag v0.2.5 && git push origin v0.2.5`):
GitHub Actions builds the server and web images for amd64 and arm64
(`ghcr.io/enzoblain/palabre`, `ghcr.io/enzoblain/palabre-web`); the release notes read the changes, then the server image line.
