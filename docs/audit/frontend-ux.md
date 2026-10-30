# Frontend and UX audit

Scope: `frontend/` (React + TypeScript + Vite, Tauri shell, nginx). Findings only, no fix is applied here.
Method: full read of `src/`, `src-tauri/`, `index.html`, `nginx.conf` and `styles.css`. Nothing was run on a real device: every mobile point is read from the code and still has to be confirmed on a phone (#96 and #105 were never tested on one).
Line numbers refer to the `dev` branch at the time of writing. Severity: critical / high / medium / low. Effort: S (under half a day), M (1 to 2 days), L (more).

## Summary

| # | Finding | Severity | Effort |
|---|---------|----------|--------|
| 1 | No tests and no linter on the frontend | high | M |
| 2 | Access token stored in clear in `localStorage`, no CSP in Tauri | high | M |
| 3 | API responses are cast, never validated | high | M |
| 4 | Silent failures: most fetch errors are swallowed | high | M |
| 5 | Mobile keyboard handling never tested on a real phone | high | S (test) / M (fixes) |
| 6 | Polling is unbounded and ignores tab visibility | high | M |
| 7 | Chat is not announced to screen readers | medium | S |
| 8 | History capped at 200 messages, no pagination | medium | M |
| 9 | Unread tracking is fragile | medium | M |
| 10 | Connection lost: no offline or reconnecting state | medium | S |
| 11 | Mobile drawer is not a real dialog | medium | S |
| 12 | Hand-written types drift from the backend | medium | M |
| 13 | Touch targets and contrast below guidelines | medium | S |
| 14 | `DocumentView` loading, error and decision flows | medium | S |
| 15 | Tauri wildcard HTTP scope and window settings | medium | S |
| 16 | Direction readability: pending requests are hard to find | medium | M |
| 17 | Visual inconsistencies (buttons, forms, feedback) | low | M |
| 18 | `App.tsx` and big components are doing too much | low | M |
| 19 | Minor code and UX nits | low | S |

## High

### 1. No tests and no linter on the frontend

- Where: `frontend/package.json:6-12` (`check` is `tsc --noEmit` plus `vite build`), `.github/workflows/ci.yml:65-90`. No test runner, no ESLint, no `react-hooks` rules. `src/util.ts:24` and `src/App.tsx` carry an `eslint-disable` comment for a tool that is not installed.
- Problem: the only guard is the type check. The riskiest logic is untested: unread counting (`App.tsx:63-121`), `spreadAccounts` (`util.ts:56`, must mirror `backend/app/accounts.py`), the Markdown mention plugin (`Markdown.tsx:13-42`), `normalizeServer`, `parseDate`, team validation (`TeamEditor.tsx:48-60`). The hand-written `useEffect` dependency lists (`App.tsx:75,89`, `ConversationView.tsx:226`) are never checked.
- Fix: add Vitest plus Testing Library for the pure helpers and the `RequestBox`/`Composer` flows; add ESLint with `react-hooks/exhaustive-deps` and `jsx-a11y`; run both in `npm run check`. Add one Playwright smoke test (connect, open direction, send, answer a request) at a phone viewport.
- Effort: M.

### 2. Access token in clear in `localStorage`, and no CSP

- Where: `src/api.ts:127-152` (`palabre.connection` holds server and bearer token), `src-tauri/tauri.conf.json:25-27` (`"csp": null`), `Markdown.tsx:74` (renders agent-written Markdown).
- Problem: the admin token is readable by any script in the page. Agents write the Markdown the UI renders; `react-markdown` escapes HTML by default, which is good, but with no CSP any future slip (for example adding `rehype-raw`, or a dependency compromise) gives full access to the token and therefore to the whole company. In Tauri the same applies, with the `http:default` capability on top (see 15). The token is also in the `Connect` form as `type="password"` with no `autocomplete` hint.
- Fix: set a strict CSP in `tauri.conf.json` (`default-src 'self'`, `connect-src` limited to what Tauri needs, `img-src 'self' data:`) and the same as a header in `nginx.conf`; in the desktop app keep the token in the OS keychain or a Tauri store rather than `localStorage`; add `autoComplete="off"` / `current-password` deliberately on the token field. Add a comment and a test that `rehype-raw` is never enabled.
- Effort: M. Needs Inès (security) to review.

### 3. API responses are cast, never validated

- Where: `src/api.ts:258` (`await res.json()) as T`), `src/api.ts:193` (`JSON.parse(raw) as Connection`), `src/components/DocumentView.tsx:25` (`roomDocument<T>` lets the caller pick the type), `src/router.ts:16` (`as "report"`).
- Problem: strict mode is on (`tsconfig.json`), but the type system stops at the network edge. Any backend change that renames or nulls a field compiles fine and crashes at runtime (for example `m.rooms.map`, `p.name.slice`). A corrupted `localStorage` value passes as a `Connection` and yields `undefined/api/...` requests.
- Fix: validate at the boundary. Either generate types from the FastAPI OpenAPI schema (see 12) or add a small schema library (zod or valibot) for the handful of hot responses (`ProjectDetail`, `Message`, `EmployeeStatus`) and for the stored connection. At minimum check `typeof server === "string"` in `readConnection`.
- Effort: M.

### 4. Silent failures: errors are swallowed

- Where: `src/util.ts:13-16` (`usePolling` drops every error), `src/App.tsx:138,144` (`.catch(() => {})` on projects and settings), `ConversationView.tsx:226` (direction link), `NewProject.tsx:56,67,68` (names, personality, roles), `App.tsx:44-51` (`useProject` has no retry), `src/App.tsx:171-175` (credits banner).
- Problem: when the server is down or slow, the UI keeps showing stale data with no sign of it. Concrete cases: the sidebar status dots and the "N working" counter freeze; the pending badge for the lead's requests (`App.tsx:152-159`) stays at its last value, so a request can be missed; the credits banner disappears if the poll fails; `NewProject` can be submitted while `personality`/`roles` failed to load, and the "Build my own" tab is then disabled with no explanation. If the first settings call fails, `boss_name` stays empty and the user is not redirected to Settings. `useProject` shows an error but offers no retry: the user has to reload.
- Fix: give `usePolling` an `onError` and expose a `failing` state; show one global "Connection problem, retrying" strip (see 10); add a Retry button to the error states of `useProject` and `NewProject`; surface catalog load failures in the form.
- Effort: M.

### 5. Mobile keyboard handling is unverified on real devices

- Where: `src/main.tsx:21-39` (`visualViewport` sync), `styles.css:56-59` (`#root` is `position: fixed` with `--app-height`), `styles.css:261` (`field-sizing: content` on the composer), `index.html:5` (`interactive-widget=resizes-content`), `styles.css:374-401`.
- Problem: three mechanisms fight over the same job (the `dvh` rule, `interactive-widget`, and the JS `--app-height`). `window.scrollTo(0, 0)` runs on every `scroll` event, which can fight the browser when it scrolls a focused field into view. `field-sizing: content` is not supported on Safari before 26 and Firefox: there the composer will not grow. `stickToBottom` (`ConversationView.tsx:290-298`) is not re-applied when the viewport height changes, so opening the keyboard can hide the newest messages. The `RequestBox` textarea sits inside the scrolling list: on iOS the form can end up under the keyboard. Safe-area insets (`env(safe-area-inset-*)`) are not used anywhere, so the composer can sit under the home indicator and the notch overlaps the mobile bar in standalone mode. The viewport meta has no `viewport-fit=cover`.
- Fix: test #96 and #105 on at least one iPhone (Safari) and one Android (Chrome) and record the result. Keep one mechanism (the `visualViewport` one is the most portable) and drop the others; re-stick to bottom on `visualViewport` resize; add a JS fallback for auto-growing the textarea; add safe-area padding to `.mobile-bar` and `.composer`. Make the open `RequestBox` form call `scrollIntoView({block: "nearest"})`.
- Effort: S for the test pass, M for the fixes it will probably reveal.

### 6. Polling is unbounded and ignores tab visibility

- Where: `src/util.ts:4-26`; call sites `App.tsx:152,162,173` (3s, 4s, 15s), `App.tsx:93` (4s, one request per direction conversation), `ConversationView.tsx:274` (2s), `ConversationView.tsx:255` (4s), `DocumentView.tsx:26` (8s).
- Problem: roughly 4 to 6 requests every few seconds per open client, forever, even when the tab is hidden or the phone is locked. On mobile this drains battery and data; on the server each client adds constant load. `PENDING_POLL_MS` re-downloads up to 200 messages of the direction conversation every 4s (`App.tsx:154`) just to count pending requests, while `useUnread` fetches the same conversation again. There is no backoff when requests fail (see 4) and no jitter. Two timers for the same data (pending and unread) can disagree.
- Fix: pause polling on `document.visibilityState === "hidden"` and refresh once on return; back off exponentially on errors; merge pending and unread in one poll. Longer term, ask the backend for a single `/projects/{id}/summary` endpoint or Server-Sent Events (the backend is FastAPI, SSE is cheap) to replace the timers.
- Effort: M (visibility and backoff: S; SSE: L and a backend task).

## Medium

### 7. The chat is not announced to screen readers

- Where: `ConversationView.tsx:333` (`.messages` is a plain `div`), `ConversationView.tsx:359-361` (typing indicator has no live region), `ConversationView.tsx:362` (`composer-error` has no `role="alert"`, unlike `RequestBox` line 110), `App.tsx:221` (the sidebar toggle has no `aria-expanded`/`aria-controls`).
- Problem: new messages, the "X is thinking" line and send errors are silent for assistive tech. Message authorship is only visual for grouped messages. The `mentions-me` highlight (`styles.css:229`) is color only: no text says "mentions you".
- Fix: `role="log"` plus `aria-live="polite"` and `aria-relevant="additions"` on `.messages`; `role="status"` on `.typing`; `role="alert"` on `composer-error`; a visually hidden "mentions you" label; `aria-expanded` on the menu button. Make each message an `article` with an accessible name (author, time).
- Effort: S.

### 8. History is capped at 200 messages, with no way to load older ones

- Where: `src/api.ts:174-177` (`limit=200`), `ConversationView.tsx:274-288`, `App.tsx:154`.
- Problem: opening a long conversation shows the 200 messages the server returns, and nothing lets the CEO scroll further back. Direction can become the longest thread of the product, and the CEO cannot find an old decision there. Pending counting (`App.tsx:154-155`) also only sees those 200 messages: an old unanswered request beyond the window is invisible and the badge is wrong. Conversely the in-memory list grows without bound during a long session and every poll re-renders it (only `MessageRow` is memoized).
- Fix: add `before_id` pagination (backend task) and a "Load earlier messages" control that keeps the scroll position; add a search or "jump to pending" shortcut; virtualise the list above a few hundred rows if needed. For the badge, ask the backend for a pending count instead of deriving it.
- Effort: M (plus a small backend change).

### 9. Unread tracking is fragile

- Where: `src/App.tsx:60-121`.
- Problem: state lives in a `ref` and in `localStorage` keys that are never cleaned (`palabre.seen.<id>`); a deleted project leaves its keys forever, and the keys are not scoped by server, so two servers with overlapping conversation ids share read state. `markRead` and `publish` are recreated each render and used inside an effect with a partial dependency list (`[activeConversation]`), so they depend on closure luck. `localStorage` access is not in a `try`, unlike `api.ts` (private mode or a full quota throws inside the poll and the error is silently swallowed, so unread silently stops). The unread count never reaches the page title or the app icon, so a CEO on another tab does not know the lead answered.
- Fix: move read state into one small module (`seen.ts`) with a try/catch, a server-scoped key and cleanup on project deletion; unit-test it; show the total unread/pending count in `document.title` and use the Notification API (opt-in) for pending requests.
- Effort: M.

### 10. No offline or reconnecting state

- Where: `src/api.ts:185-187` (network errors become `ApiError(0, ...)`), `App.tsx:18-35`, `Connect.tsx`.
- Problem: only a 401 is handled globally (`api.ts:205`, and it signs the user out). A server restart or a Wi-Fi drop is invisible; after it, a send can fail with a message the user must interpret (`Cannot reach the server at ...`) and the draft is kept, which is good, but there is no automatic retry. A 401 caused by a transient proxy error would log the CEO out and clear the stored connection with no confirmation.
- Fix: a global connection banner driven by polling failures (`status === 0`), retried automatically; on 401 keep the server address and only clear the token, with a message explaining why the user is back on the login screen.
- Effort: S.

### 11. The mobile drawer is not a real dialog

- Where: `App.tsx:218-229`, `styles.css:377-387`.
- Problem: the sidebar slides over the page but the content behind stays focusable and readable by screen readers; there is no focus trap, no `Escape` to close, focus is not moved into the drawer on open nor returned to the menu button on close. The off-screen drawer (`translateX(-100%)`) stays in the tab order while closed on mobile, so keyboard users tab into invisible links. The backdrop is a bare `div` with a click handler.
- Fix: on small screens set `inert` (or `visibility: hidden` after the transition) on the closed drawer and on `main` while it is open; handle `Escape`; manage focus. Consider the native `<dialog>`.
- Effort: S.

### 12. Hand-written types drift from the backend

- Where: `src/api.ts:10-121` ("mirror `backend/app/api/schemas.py`" is a comment, not a check), `DocumentView.tsx:9-16` (local `Question`, `Task`, `RoomDocument` types), `Message.request_kind: string | null`, `Project.mode: string`, `Task.status: string` (`DocumentView.tsx:10`).
- Problem: duplicated contracts. `request_kind` and `status` are free strings, so a typo in a comparison compiles. `ProjectDetail` and `Conversation` are used but defined elsewhere in the file and are easy to desynchronise from `schemas.py`.
- Fix: generate `api.d.ts` from the FastAPI OpenAPI document in a script (`openapi-typescript`) and check in CI that it is up to date; narrow the string fields to unions; move the document types into `api.ts`.
- Effort: M.

### 13. Touch targets and colour contrast

- Where: `styles.css:87` (`.btn-small` has `4px 10px` padding and 13px text), `styles.css:90` (`.icon-btn`), `styles.css:278` (`.account-tag` at 10px), `styles.css:284` (badge 18px high, 11px text), `styles.css:141` (12px status text), `styles.css:6,38` (`--muted` on `--bg`/`--sidebar`), `styles.css:19-21` (`mention-me` colours), `styles.css:16` (`--waiting`).
- Problem: `RequestBox` buttons are correctly 44px (`styles.css:299`), but the rest of the app is not: delete, branch and period buttons in Settings, the phase links, the account select (`padding: 3px 6px`), the quick-mention member buttons and the unread badges are under 44x44 / 24x24 on a phone. Text at 10 to 12px is below comfortable reading size. `--muted` (#6c6c7a) on `--sidebar` (#f1f1f5) is about 4.4:1, just under AA for small text; the dark `--resting` dot (#5c5c6a) is under 3:1 against `--sidebar` and carries state. Status dots rely on colour; the sidebar text label next to them helps, the lone live dot is labelled (`Sidebar.tsx:154`).
- Fix: raise a global minimum of 44px on touch (`@media (pointer: coarse)`), a 12px text floor, and run an automated contrast pass (axe) on both themes; darken `--muted` slightly in light mode.
- Effort: S.

### 14. `DocumentView`: loading, error and decision flows

- Where: `DocumentView.tsx:22-37,72-86`.
- Problem: `load()` errors reject inside `usePolling` and vanish, so a failed first load shows "Loading…" forever (the `error` state is only set by `decide`). Validating a decision, which can merge a PR into production (`Merge PR #n`, line 81), runs on one click with no confirmation, no busy state and no double-click guard. The two buttons stay enabled while the request is in flight. `ConversationView` has all of that for requests; here it is missing. The rejected list shows no rationale, and `t.status.replace("_", " ")` only replaces the first underscore.
- Fix: error state with retry for the first load; a confirm step (or an undo window) for merge decisions; `busy` flag per decision; `replaceAll` or a status label map.
- Effort: S.

### 15. Tauri: wildcard HTTP scope and window settings

- Where: `src-tauri/capabilities/default.json:9-16`, `src-tauri/tauri.conf.json:11-20`, `Markdown.tsx:44-47`.
- Problem: the capability allows requests to any http(s) host. This is deliberate (the user hosts the server anywhere) but it also means a compromised front can reach any LAN service; plain `http://` is allowed, so the bearer token travels in clear over the network, and nothing in `Connect` warns about it when the address is not a LAN one. The four URL patterns are redundant (`http://*/*` already covers the others). The `mailto:` and `https:` links in agent messages go through `opener:default` with no allow-list: `openUrl` is only called after the `^(https?:|mailto:)` test, which is good, but the capability itself would accept anything the front asks. There is no explicit window state persistence, no auto-update config and no signing config for release builds, `minWidth: 760` equals the mobile breakpoint so the desktop window never reaches the mobile layout (intended, but undocumented). The `inTauri` test is duplicated (`api.ts:5`, `Markdown.tsx:45`).
- Fix: dedupe the scope; show a warning in `Connect` when the address is `http://` and not a private IP; restrict the `opener` scope to `https`/`mailto`; centralise `inTauri` in one module; document the updater/signing plan.
- Effort: S.

### 16. Direction readability: pending requests are hard to find

- Where: `Sidebar.tsx:21-24,155-157`, `ConversationView.tsx:35-114,141`, `styles.css:229`.
- Problem: the sidebar shows "N waiting for you", but opening Direction lands at the bottom of the thread and the pending request can be hundreds of messages above (see 8). There is no "jump to next request" control and no pinned list of open requests. Requests render as ordinary messages with the buttons below long Markdown; the lead's long messages have no collapse. `grouped` messages (same author in a row, `ConversationView.tsx:353`) hide the timestamp for the whole group even when hours apart, and group on name only, so a message after a long gap reads as a continuation. System lines and agents' lines look alike apart from a muted colour. The CEO's own messages are visually identical to the team's in layout (only a small "CEO" label), so a long exchange is hard to scan. The "thinking…" line names agents but not what they do.
- Fix: a sticky "N requests waiting, jump to the first" bar in direction; break groups after a time gap (for example 5 minutes) and show the time on hover; collapse messages beyond ~20 lines with "Show more"; align the CEO's messages differently or tint them; show the doing-what from `EmployeeStatus.kind` in the typing line.
- Effort: M.

## Low

### 17. Visual inconsistencies

- Where: `Settings.tsx:41,85,240` (labels, select and input styles differ: bare `select` vs `input` rules at `styles.css:74-78` and `267-269`), `Settings.tsx:46,90,216` (three feedback patterns: inline `success`/`error` span, a note under the field, a `role="status"` span), `Settings.tsx:194-200` vs `DocumentView.tsx:80-83` (confirm for deletion yes, for production merges no), `Connect.tsx:43`/`Settings.tsx:127` (errors with and without `role="alert"`), `ConversationView.tsx:24` and `DocumentView.tsx:89,115` (`✓` and `→` characters in text instead of icons), `Icons.tsx` (no close or check icon, so glyphs are used).
- Problem: small mismatches in spacing, focus styles (`input:focus` uses a ring, `select:focus` only changes the border, the composer uses `:focus-within`), feedback placement and button sizes (`btn` vs `btn-small` mixed in the same row). Some strings are produced by code rather than a single place, so all texts are hard-coded English with no i18n (the backend supports a team language but the UI itself does not follow it).
- Fix: a tiny set of shared components (`Field`, `Feedback`, `ConfirmButton`, `Select`) and one focus-ring rule; decide whether the UI language should follow the team language and, if yes, extract strings.
- Effort: M.

### 18. Large components do too much

- Where: `src/App.tsx` (`Shell` handles routing, settings, projects, pending, statuses, credits, unread and layout, lines 123-236), `ConversationView.tsx` (380 lines, six components), `Settings.tsx` (421 lines, seven sections), `NewProject.tsx` (249 lines, a dozen `useState`).
- Problem: harder to test and to change safely (see 1); data fetching is mixed with markup, with no shared cache, so Settings refetches every project's detail (`Settings.tsx:100-105`, one request per project on every render of `projects`) and `useProject` refetches everything on each route change to another project.
- Fix: extract hooks (`useDirectionPending`, `useTeamStatus`, `useCredits`) and split files per section; consider TanStack Query for the cache, retries, polling and visibility handling in one place (this would also solve 4 and 6; a proven library fits the project's "reuse" rule better than the custom hook).
- Effort: M.

### 19. Minor nits

- `App.tsx:126-128`: the default settings object claims `language: "French"` before the server answers; use `null` and a loading state.
- `ConversationView.tsx:248`: `isGeneral` logic is hard to read and returns true for direction rooms, which the intro text then treats as the general channel.
- `ConversationView.tsx:166-173`: if `onSend` throws, `sending` stays true and the composer is stuck (no `finally`).
- `ConversationView.tsx:180`: Enter always sends, with no option for Ctrl+Enter; on a phone keyboard, Enter should insert a newline (the send button is there). Needs a decision.
- `Sidebar.tsx:150-152`: a room with no conversation renders an `<a>` without `href`, which is not focusable and not a link.
- `Sidebar.tsx:106-122`: a member `<button>` mentions on click but gives no focus feedback that the composer got the text, and does nothing on a read-only channel (the composer does not exist there).
- `Avatar.tsx:7`: `name.slice(0, 1)` splits a surrogate pair for names starting with an emoji or rare script.
- `util.ts:36`: `toLocaleString` with `undefined` locale mixes the system locale with the English UI.
- `router.ts:6-28`: hash routing is fine, but an unknown hash silently shows Home, and a project that was deleted shows "Loading…" or an error with no way back except the browser button.
- `Settings.tsx:56`: shows the full server URL, which may contain credentials if the user typed any; `normalizeServer` does not strip them.
- `index.html`: `lang="en"` and no `theme-color`, no `manifest`, no icons for "Add to home screen", which is the likely way to use it on a phone.
- `nginx.conf`: no security headers (`X-Content-Type-Options`, `Referrer-Policy`, `Content-Security-Policy`, `X-Frame-Options`), no gzip, `index.html` is not marked `no-cache`, so a new release can be served stale.
- Effort: S for each.

## Suggested order

1. 5 (device test) and 4, because they affect daily use and are cheap to verify.
2. 2 and 3 with Inès, then 1 so the fixes ship with tests.
3. 6, 8, 16 together: they are the same area (conversation loading) and share a backend change.
4. The medium accessibility items (7, 11, 13) in one pass.
5. The low items as cleanup when touching the same files.
