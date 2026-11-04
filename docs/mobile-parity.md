# Mobile parity with the web app

The CEO wants the [mobile app](mobile.md) to do everything the web app does. This file is the exhaustive list of the
differences between `frontend/src` and `mobile/app` + `mobile/src`, grouped in **batches**: each batch can be delivered
on its own and is meant to become one task (or a few). It was written from a read of every file of `frontend/src`
(screens, components and helper modules) against the mobile code at version 0.30.5.

The web app has no screen for tasks, decisions, monitoring, the catalog or releases (they exist only in the API and the
agents' tools), so there is nothing to port for them.

Mobile placements are adaptations to a phone (iMessage-like, see [Mobile UI](mobile-ui.md)), not a copy of the desktop
layout. Keyboard shortcuts, hover states, the desktop team column and URL routing have no mobile equivalent on purpose.

## How to read the tables

- **State**: `present` (same behavior), `partial` (exists, something is missing), `absent`, or `in progress` (covered by
  a running task, see the last section).
- **Priority**: P1 = the CEO sees the gap on every use, P2 = regular use, P3 = rare or setup-time use.
- **Web source** names the file in `frontend/src`.

## Batches

| Batch | Content | Priority | Depends on |
|---|---|---|---|
| 1 | Conversation screen basics: info sheet, typing indicator (done), scroll behavior (pending) | P1 | none |
| 2 | Message content and actions: Markdown, mentions, copy, sent time, system messages | P1 | batch 1 (same screen) |
| 3 | App shell and project list: tab bar, edit mode and deletion, credits banner, first-run name | P1 | none |
| 4 | Settings screen: name, language, connected devices, Claude accounts, server | P2 | batch 3 (tab bar) |
| 5 | Project info screen: name, branch, description, git link, deletion | P2 | batch 3 |
| 6 | Team management of a project: members, jobs, personalities | P3 | batch 5 |
| 7 | New project: form, automatic or manual team, team editor | P3 | batch 3, shares the pickers of batch 6 |

Batches 1 and 3 are independent. 6 and 7 share the job and personality pickers: build them once, in whichever of the two
comes first, as shared components.

## Batch 1: conversation screen basics (only the scroll behavior is pending)

Web source: `ConversationView.tsx`, `ConversationTeam.tsx`, `MessageBubble.tsx` (typing dots).

| Web feature | State in the app | Planned place on mobile | Priority |
|---|---|---|---|
| Conversation header: title (hidden in the direction room) and member count | present | Header "Info" button opening a bottom sheet | P1 |
| Team column: members sorted lead first, avatar, name, title | present | Members list inside the info sheet (no side column on a phone) | P1 |
| Room objective and summary | present | Same info sheet | P1 |
| Typing dots while the lead writes (direction room only) | present | Dots at the end of the message list | P1 |
| Open on the latest message, stay at the bottom after sending or on a new message, do not force down when the user scrolled up | in progress | Message list scroll behavior | P1 |
| Info sheet refreshed while open (objective and summary are read once) | partial | Re-read the room with the message poll | P3 |

## Batch 2: message content and actions

Web source: `MessageBubble.tsx`, `Markdown.tsx`, `ConversationView.tsx` (composer, `MessageList`), `util.ts`.

| Web feature | State in the app | Planned place on mobile | Priority |
|---|---|---|---|
| Message body rendered as Markdown (lists, code, links, tables via GFM, line breaks) | absent (plain text) | Native rendering of the same Markdown subset inside the bubble | P1 |
| `@Name` mentions highlighted, and a different style when the boss is mentioned (`bossNames`, `mention-me`) | absent | Colored span in the bubble; bubble tinted when it mentions the boss | P1 |
| Links open outside the app, only `http(s)` and `mailto` | absent | Open with the system browser, same allow-list | P1 |
| Author name and job title above a bubble | partial (name only, no title) | Title next to the name, from the project employees | P2 |
| Grouping of consecutive messages from one author | present | none | |
| Messages from the platform (`is_system`) labelled "Platform" | partial (no label) | Centered system line with the label | P2 |
| Copy a message (long press, context menu, "⋯" button) with copied or failed feedback | absent | Long press opens an action sheet with Copy | P1 |
| Info action: full date and time of sending | absent | Second entry of the same action sheet | P2 |
| Composer placeholder naming the project and the boss, and a different one in an empty conversation | partial (fixed text) | Same placeholders | P3 |
| Empty conversation intro (project name, lead name and title) | absent | Intro text in the list's empty state | P2 |
| Initial loading state of the list | present (skeleton) | none | |
| Send error shown under the composer, draft kept on failure | partial (failed bubble with retry; the draft is cleared on send) | Keep the retry bubble, no change needed unless the draft must survive | P3 |
| Tap a teammate to insert `@Name` in the composer | absent (the web does it from the desktop team column) | Tap a member in the info sheet inserts the mention | P2 |
| Enter inserts a newline on touch screens, the button sends | present (multiline field and send button) | none | |
| Read marker: opening the direction room marks it read, and each new message while open | present | none | |
| "Lift the limit" button (restarts the anti-loop window of the conversation) | absent | Action in the info sheet, with the result message | P2 |

## Batch 3: app shell and project list

Web source: `App.tsx`, `BottomBar.tsx`, `Projects.tsx`, `ProjectList.tsx`, `ProjectsEditing.tsx`, `navigation.ts`,
`router.ts`, `layout.ts`.

| Web feature | State in the app | Planned place on mobile | Priority |
|---|---|---|---|
| Bottom bar with Projects, New project, Settings | present (three tabs; New project and Settings show a placeholder until batches 4 and 7) | none | |
| Project list: avatar, name, last message preview, unread badge | present | none | |
| Loading skeleton, error with retry, empty state with a "create project" button | partial (skeleton, error banner and empty text; no create button) | Create button in the empty state, leads to batch 7 | P2 |
| Search field (web: only above 8 projects) | present (always shown, matches on the name) | none | |
| Most recently opened project first | absent | Remember the last opened id in the app storage | P3 |
| Edit mode: tick several projects, delete them after a confirmation, error message | absent | "Edit" button in the list header, row selection circles, destructive confirmation sheet | P2 |
| Opening a project lands in the conversation with the lead (direction room) | present (the list opens the direction conversation directly) | none | |
| Back arrow leading to the parent screen | present | none | |
| Credits banner: Claude accounts out of credits, when they come back, per account if several | absent | Banner at the top of the root screens, polled every 15 s | P1 |
| First run: no boss name yet opens Settings | absent | Redirect to the name field of batch 4 | P2 |
| Team language drives the interface language | absent (the app follows the phone language) | Keep the phone language, a deliberate difference; revisit with batch 4 | P3 |
| Polling of the project list every 5 s | present | none | |
| Unauthorized answer sends back to the sign-in screen | present | none | |
| Sign-in: server URL, token, error and busy state | present (pairs the phone and stores a device token) | none | |
| Server field hidden when the page is served by the backend | n/a (web only) | none | |

## Batch 4: settings screen

Web source: `Settings.tsx`, `ConnectedDevices.tsx`, `ConfirmDialog.tsx`, `AccountSelect.tsx`, `devices.ts`, `jobs.ts`
(`spreadAccounts`).

| Web feature | State in the app | Planned place on mobile | Priority |
|---|---|---|---|
| Settings screen reachable from the navigation | absent | Third tab of the bar (batch 3) | P2 |
| Boss name: edit, save, success and error messages, required hint | absent | Grouped form row, save in the navigation bar | P2 |
| Team language: pick among the server languages, saved on change | absent | Picker row | P3 |
| Connected devices: list with name, added, last used, expires; "never used" | absent (the API client already has `listDevices` and `revokeDevice`) | List section | P2 |
| Revoke a device after a confirmation, status message, focus handling | absent | Swipe or button then a confirmation alert; the current phone should warn it signs out | P2 |
| Loading, error with retry and empty state of the devices list | absent | Same three states | P2 |
| Claude accounts: count explanation, and per employee account choice per project when there are several | absent | One section per project, picker per employee | P3 |
| Automatic account spreading shown as the effective account | absent | Label of the picker's first option | P3 |
| Server: connected URL and a disconnect button | partial (sign-out exists in the session but has no screen) | Button in the Server section, with confirmation | P1 |

## Batch 5: project info screen

Web source: `ProjectInfo.tsx` (`ProjectBar`, `ProjectForm`, `DeleteProject`).

| Web feature | State in the app | Planned place on mobile | Priority |
|---|---|---|---|
| Project screen reachable from a conversation (info icon) | partial (the conversation info sheet exists, not the project page) | Link at the bottom of the info sheet, or a pushed screen | P2 |
| Edit name (100 characters) and main branch, saved together, backend warning shown | absent | Form with a save button, inline status | P2 |
| Unsaved-change detection that enables the save button | absent | same | P2 |
| Description (the direction room objective) with a hint to change it by asking the lead | absent (objective shown read-only in the conversation info sheet) | Text block on the page | P3 |
| Git link opened in a new tab, or "no git" text | absent | Opens with the system browser | P3 |
| Delete the project after a confirmation, with error and busy state | absent | Destructive button at the bottom with a confirmation alert, then back to the list | P2 |
| Loading and load error of the project | partial (conversation screen only) | Same states | P2 |

## Batch 6: team management of a project

Web source: `TeamSection.tsx`, `JobPicker.tsx`, `PersonalityPicker.tsx`, `presets.ts`, `jobs.ts`.

| Web feature | State in the app | Planned place on mobile | Priority |
|---|---|---|---|
| Team list sorted by name: avatar, name, job title, quirks | partial (members shown in the conversation info sheet, without quirks) | Section of the project page (batch 5) | P3 |
| Lead badge, the lead cannot be edited or removed | absent | same | P3 |
| Edit a member: jobs and personality, hint about what changes | absent | Pushed form screen | P3 |
| Remove a member after a confirmation | absent | Swipe action with a confirmation alert | P3 |
| Add a member: jobs and personality | absent | Pushed form screen | P3 |
| Job picker: grouped by category (collapsible), search, several jobs per member, details (mission, responsibilities, forbidden, deliverables, tools), model and effort | absent | Searchable list, details in a sheet | P3 |
| Personality picker: radio list, search without accents, "random" option, empty and no-match messages | absent | Searchable single-choice list | P3 |
| Catalog loading and failure of the team section | absent | Loading and retry states | P3 |
| `/catalog` calls: roles, personalities, limits, names | absent in `src/api` | Add the typed calls to the client | P3 |

## Batch 7: new project

Web source: `NewProject.tsx`, `CompanyTeamSection.tsx`, `TeamEditor.tsx`, `AccountSelect.tsx`, `presets.ts`, `jobs.ts`.

| Web feature | State in the app | Planned place on mobile | Priority |
|---|---|---|---|
| New project screen | absent | Second tab of the bar, or a "+" in the list header (decision for batch 3) | P3 |
| Name (200 characters) and GitHub repository URL with live validation | absent | Form with inline error | P3 |
| Team by description (automatic): description text and head count within the server limits | absent | Segmented control "Automatic / Manual" | P3 |
| Team by hand (manual): lead locked first, name per member with a random free name button, jobs, personality, model, Claude account | absent | List of member rows opening a form (shares batch 6 pickers) | P3 |
| Team size limit warning and help, minimum size, problems list (no lead, duplicate or invalid name, no job) | absent | Inline messages above the submit button | P3 |
| Presets failing to load with retry; manual tab disabled until the catalog is loaded | absent | same | P3 |
| Submit, busy state, API error, opens the new project | absent | Navigate to the new project's conversation | P3 |
| Cancel | absent | Back button | P3 |

## Cross-cutting differences

Web source: `api.ts`, `i18n/`, `util.ts`, `main.tsx`, `styles.css`, `Icons.tsx`, `Avatar.tsx`.

| Web feature | State in the app | Planned place on mobile | Priority |
|---|---|---|---|
| Typed API client | partial: `src/api` covers sign-in, devices, projects (list and detail), conversations, messages and read marker. Missing for the batches: settings, update and delete project, employees, catalog, orchestrator status, rate limit lift, accounts | Add calls batch by batch, keeping the client shared with the web app | P1 |
| French and English interface | present (phone language) | Same keys to add per batch, with the key check | P1 |
| Avatar with color from the name | present (initials and color) | none | |
| Dark and light themes | present | none | |
| Text size accessibility | present (`maxFontSizeMultiplier`) | none | |
| Long-running polling that pauses in the background | present (`usePolling`) | none | |
| Push notifications | absent on both web and app; needs backend work (see [Mobile app](mobile.md)) | Out of this inventory, separate task | P2 |
| Hash router with direct URLs, browser back button | n/a | Expo Router paths | |
| Desktop breakpoint, hover, keyboard shortcuts (Escape closes, Tab trap, Enter sends) | n/a | Replaced by gestures and the system keyboard | |
| Version display, service worker, favicon | n/a | none | |

## Already covered by other tasks

- Task 519 (done, merged): conversation info sheet, typing indicator. Its review notes that the bottom tab bar was
  not delivered: it is listed in batch 3.
- Task 520 (in progress): scroll behavior of the conversation (batch 1).

## Suggested order

Batch 3 first (tab bar and the sign-out path, the CEO's explicit complaint), then 2 (reading the messages properly),
then 4, 5, 6, 7. Batches 6 and 7 are setup-time features and can wait.
