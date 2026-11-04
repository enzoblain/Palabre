# Mockup: Apple mode screens

Spec of the three screens of [Apple mode](apple-mode.md): project type choice at creation, state of the builder Mac in the settings, and the Swift build result on a task. All visible texts are French and go through the app's translation mechanism. The web app implements screens 2 and 3 and the build block of screen 4 (see [Implementation status](#7-implementation-status)).

## 1. Principles

- Everything keyboard-reachable, visible focus, tap targets of at least 44px.
- A state is never carried by color alone: always an icon and a written label.
- Contrast of at least 4.5:1 for text, 3:1 for icons and borders.
- Live changes (Mac going offline, build ending) are announced in a `role="status"` region (`aria-live="polite"`).
- Build logs and failure messages are attacker-controlled: rendered as plain text, never as HTML.
- Data comes from the backend API (`platform`, host state, `apple_jobs`); no state is guessed client-side.
- Icons are the app's SVG icons, `aria-hidden`, next to a visible word that is the accessible name. No emoji or Unicode glyph (⏳ ✔ ✖ ⚠ ⊘ ● ○ in the sketches below only stand for the icons: they render differently per platform).
- Every remark of the reviews of the first version is either integrated below or answered in [Review notes](#6-review-notes).

## 2. Project type choice (project creation)

```
Type de projet
(•) Standard
    Un projet classique : code, documentation, recherche…
( ) Apple – Swift        [désactivé]
    Application iPhone en Swift, compilée et testée sur un Mac dédié.
    ⚠ Mac non connecté. Connecter un Mac
```

- Radio group (`fieldset` + `legend` "Type de projet"), "Standard" selected by default. Maps to `platform` = `generic` | `apple`.
- "Apple – Swift" is enabled only when the server has Apple mode on and at least one Mac is connected.
- When disabled: the radio uses `aria-disabled="true"` (not `disabled`, which removes it from the tab order and hides the reason from keyboard users). It stays focusable, selecting it does nothing, and its help text is linked with `aria-describedby` and always visible (no tooltip, nothing hover-only). The reason is written, with an icon: "Mac non connecté".
- The "Connecter un Mac" link is a real link to the Mac section of the settings (screen 3), outside the `label` (a screen reader announces the label only) and in the tab order right after the radio. If Apple mode is off on the server, the reason reads "Mode Apple désactivé sur ce serveur" and there is no link.
- Loading: while the Mac state loads, the radio is `aria-disabled` with "Vérification du Mac…".
- Error (state cannot be loaded): "Impossible de vérifier le Mac. Réessayer" (button), the radio stays `aria-disabled`.
- Creation refused by the server (`platform=apple` without a Mac): the error is shown above the submit button, `role="alert"`, with the same link.
- Once chosen, "Apple – Swift" shows an info line: "Le projet devra contenir un fichier .palabre/apple.toml."

## 3. Mac builder state (settings)

Section "Mac de build" in the settings.

```
Mac de build
● Connecté   · build-mac-1 · vu il y a 12 s
  Builds en cours : 1 / 2 · File d'attente : 0
  [Révoquer ce Mac]

○ Hors ligne · build-mac-1 · vu il y a 3 h
  Les builds Swift restent en attente tant que le Mac est hors ligne.
  [Générer un code de connexion]
```

- Two states, each with an icon and a text: "Connecté" (filled dot ● + text) and "Hors ligne" (empty dot ○ + text). Last-seen is relative time with the full date in a `title`/`<time datetime>`.
- Connected: name, builds running over the maximum ("1 / 2"), queue length, all as text.
- Offline: the consequence is written. The state is also announced in the live region: "Le Mac est hors ligne".
- Several Macs: one block per Mac, ordered by last seen (most recent first). Each block has its own state, its own "Révoquer" button (named "Révoquer build-mac-1" for screen readers) and the live-region announcement names the Mac ("build-mac-2 est hors ligne"). "Générer un code de connexion" is shown once, under the list.
- No Mac enrolled (empty state): "Aucun Mac connecté. Un Mac Apple silicon dédié compile et teste les projets Swift." and the button "Générer un code de connexion".
- "Générer un code de connexion" opens a dialog showing the one-time code once, with its lifetime ("valable 10 minutes" in the sketch is only an example: the duration always comes from the API, never hardcoded), a "Copier" button ("Copié" announced in the live region) and the instruction to enter it on the Mac. The code is plain selectable text (not an image, not `user-select: none`), so it can be copied by hand too.
  - Both dialogs (code and revocation) are `role="dialog"` with `aria-modal="true"`, a visible title ("Code de connexion", "Révoquer ce Mac") and `aria-labelledby` pointing to it. Focus goes into the dialog, `Tab` stays inside, `Escape` closes it, focus returns to the button that opened it.
  - Generating: the button is `aria-disabled` with "Génération…". Error: "Impossible de générer le code. Réessayer", `role="alert"`.
  - Expired (the lifetime from the API ends while the dialog is open): the code is replaced by "Code expiré" and a "Générer un nouveau code" button, announced in the live region.
- "Révoquer ce Mac" asks a confirmation ("Révoquer build-mac-1 ? Il ne pourra plus recevoir de builds. Ses builds en cours seront arrêtés.") with "Révoquer" and "Annuler"; cancel is focused by default.
  - Revoking: "Révoquer" is `aria-disabled` with "Révocation…". Error: "Impossible de révoquer le Mac. Réessayer", `role="alert"`, the dialog stays open. Success: the dialog closes and "Mac révoqué" is announced.
  - Depends on #550 (it only sets `revoked_at` today): the backend must end the builds running on a revoked Mac as `error`: their task shows "Erreur d'infrastructure" with "Relancer" (screen 4).
- Loading: skeleton with "Chargement…". Error: "Impossible de charger l'état du Mac. Réessayer".
- Visible only to users allowed to manage the server settings.

## 4. Build result on a task

Block "Build Swift" on the task page, one line for the latest job of the task head, with the job history below.

```
Build Swift   ✔ Réussi · 2 min 14 s · commit a1b2c3d
Build Swift   ✖ Échoué · 1 min 02 s · commit a1b2c3d
   2 erreurs · 3 tests en échec
   ▸ Voir le détail
Build Swift   ⚠ Erreur d'infrastructure · commit a1b2c3d
   Le Mac a cessé de répondre. Ce n'est pas un problème de code.
   [Relancer]
Build Swift   ⏳ En attente · position 2 sur la file
```

States, each with its own icon and word:

| API status | Label | Icon | Notes |
|---|---|---|---|
| `queued` | En attente · position n sur la file | clock | Position written in full ("position 2 sur la file"), also in the live region. If the Mac is offline: "En attente : le Mac est hors ligne" |
| `running` | En cours | spinner | Spinner is replaced by text with reduced motion |
| `passed` | Réussi | check | Duration |
| `failed` | Échoué | cross | Counts of errors and failed tests |
| `error` | Erreur d'infrastructure | warning | States it is not a code problem, "Relancer". The failure message says why: Mac not responding, Mac revoked, or "Délai dépassé" when the duration limit is reached |

- The statuses are exactly those of the backend (`queued`, `running`, `passed`, `failed`, `error`). A timeout is an `error` with its reason in the message, and there is no `cancelled` status until the backend has one: the front never invents a status, and an unknown value is shown as "Statut inconnu" with the raw value in plain text.
- "Relancer" is shown on an `error` result of the current commit, to the users who can act on the task (the same ones as the other task actions; read-only users do not see it). Pressing it queues a new job for the same head: the button is `aria-disabled` with "Relance…", focus stays on it, then the line switches to "En attente" and is announced in the live region. If it fails: "Impossible de relancer le build. Réessayer", `role="alert"`. A `failed` result has no "Relancer": the code must change first.
- The commit (short SHA) is always shown. A result for an old commit is labeled "Ancien commit" and never shown as the current verdict.
- "Voir le détail" is a disclosure button (`aria-expanded`): build errors and warnings, then failed tests (name, message, `file:line`), then the log tail. Everything is plain text in a monospace block, scrollable and focusable (`tabindex="0"`) with a label "Journal de build".
- Screenshots (optional): a list of images with an `alt` such as "Capture d'écran 1 sur 3" and a link to the full size. Not shown if there is none.
- Loading: "Chargement du build…". Empty (no job yet): "Aucun build pour l'instant". Error: "Impossible de charger le build. Réessayer". Log not available (retention elapsed): "Journal supprimé après n jours".
- The status change is announced in the live region ("Build réussi", "Build échoué"), for the latest job of the task head only: rows of the history never announce anything.
- Under 640px: the line wraps, the detail takes the full width.

## 5. Acceptance checklist

- Texts and error states of the three screens are written above.
- Contrast, labels, and no information carried by color alone are specified.

## 6. Review notes

Remarks of Emma and Sacha on the first version, and what was done:

- "VM en cours" is jargon: integrated, now "Builds en cours".
- Code dialog and revocation states (error, expiry, loading): integrated in section 3.
- Code lifetime from the API: integrated; "10 minutes" is only an example (the architecture doc plans about 15 minutes, the backend sets the value).
- `aria-disabled` instead of `disabled`, link outside the label: integrated in section 2.
- SVG icons instead of glyphs: integrated in section 1 and the table.
- Dialog titles and `aria-labelledby`, selectable code: integrated in section 3.
- "Relancer" behavior and who sees it: integrated in section 4.
- Running build on a revoked Mac: integrated, ends as `error` ("Erreur d'infrastructure").
- Several Macs: integrated in section 3.
- Live region limited to the latest job: integrated in section 4.
- "position 2 sur la file" in full: integrated in the table.
- Statuses aligned with the backend (`timeout` and `cancelled`): integrated, only the five statuses of the backend remain; a timeout is an `error`.
- Link from [Apple mode](apple-mode.md): done.

## 7. Implementation status

Web app (`frontend/`):

- Screen 2: `ProjectTypeChoice` in the project creation form. Apple mode off is detected from the 404 of `GET /api/apple-hosts`.
- Screen 3: `MacBuilders` in the settings (hidden while Apple mode is off), with `EnrollmentCodeDialog`. The Mac list is refreshed every 30 s. Revoked Macs are not listed.
- Screen 4: the `AppleBuild` block (status, short commit, summary, error lines as plain text, "Retry" after an infra error). The web app has no task page yet, so the block is not mounted anywhere.
- Not shown because the API does not return them yet: builds running / maximum and queue length per Mac, queue position, duration, error and test counts, screenshots, build history and the "old commit" label.
