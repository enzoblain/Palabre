# Mockup: jobs and personalities inventory (D1)

## 1. Principles

- Three areas: Jobs (grouped by category), Personalities, Team limits.
- The UI word is "job" (French UI: "métier").
- Read-only screen: fine tuning of a member stays in TeamEditor (task F2). Creating or editing jobs and presets is out of scope (repo files only, see [catalog-design.md](catalog-design.md), "Adding a job").
- Everything keyboard-reachable, visible focus, state never carried by color alone, counters always written as text.

## 2. Job picker

```
Jobs               [Search a job…]
▸ Engineering (4)
▾ Quality (2)
  ┌───────────────────────────────┐
  │ [ ] QA          sonnet · high │
  │ Checks PRs before merge.      │
  │ Tools: 6 · Show details ▾     │
  └───────────────────────────────┘
Team: 12 / 30 members
```

- Categories: management, engineering, quality, product, support, research. Collapsible groups (button with `aria-expanded`).
- A card = title, short description, model · effort, tools count. Cards are a list (`ul`/`li`).
- "Show details" is a disclosure (not a tooltip, nothing hover-only): mission, responsibilities, forbidden actions, deliverables, tools (mcp / claude). Collapsed by default.
- Native checkboxes; a member can hold several jobs.
- Under 640px: single column.

## 3. Personality presets

```
Personality   (•) Random  ( ) Pragmatic  ( ) Perfectionist  ( ) Challenger
┌ Perfectionist ───────────────────────┐
│ Cares about details, reads twice.    │
│ Rigor       ▓▓▓▓▓ +2                 │
│ Speed       ▓▓░░░ -1                 │
│ Style: concise · formal              │
│ Quirks: 2 / 5  "Cites sources"       │
└──────────────────────────────────────┘
```

- Radio group, "Random" by default.
- Levels -2..+2 always written as numbers next to the bar.
- Presets depend on the project kind (company / research).

## 4. Team limits

```
Members   12 / 30   (18 left)
Quirks    Léa: 5 / 5  ← limit reached
Rules     ✔ Exactly one ship_release holder
          ✖ No manage_channels holder
          ✖ Marc holds both merge and code
```

- Counters as "n / max" text, `role="status"` (`aria-live="polite"`). Limits come from the API, not hardcoded.
- Warning from 25 members or 4 quirks: ⚠ icon + text, not color only.
- At the limit the checkbox is disabled and a help text (`aria-describedby`) says why.
- Rules mirror "Team constraints" in [catalog-design.md](catalog-design.md).

## 5. Empty and error states

- Loading: skeleton of 3 cards (`aria-busy`).
- No job: "No job available. Jobs are added in the repository, see the README (Adding a job)." No button.
- Empty search: "No job matches "xyz"." + link "Clear search".
- No preset for this kind: only "Random" + "No predefined personality."
- Load failure: banner `role="alert"` "Could not load the catalog. [Retry]".
- 422 `UNKNOWN_PERSONALITY`: "This personality no longer exists. Pick another one or go back to Random."
- 422 team rules (30 members, 5 quirks, merge+code, single `ship_release` / `manage_channels` holder): message next to the field + summary at the top with links to the fields.

## 6. Accessibility

- Visible focus ring, AA contrast on badges, targets ≥ 24px, errors linked with `aria-describedby`.

## Out of scope

- Creating or editing jobs and presets from the UI.
