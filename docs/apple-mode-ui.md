# Mockup: Apple mode screens

Spec of the three screens of [Apple mode](apple-mode.md): project type choice at creation, state of the builder Mac in the settings, and the Swift build result on a task. All visible texts are French and go through the app's translation mechanism. Nothing here is implemented yet.

## 1. Principles

- Everything keyboard-reachable, visible focus, tap targets of at least 44px.
- A state is never carried by color alone: always an icon and a written label.
- Contrast of at least 4.5:1 for text, 3:1 for icons and borders.
- Live changes (Mac going offline, build ending) are announced in a `role="status"` region (`aria-live="polite"`).
- Build logs and failure messages are attacker-controlled: rendered as plain text, never as HTML.
- Data comes from the backend API (`platform`, host state, `apple_jobs`); no state is guessed client-side.

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
- When disabled: the radio uses `disabled`, its help text is linked with `aria-describedby` and always visible (no tooltip, nothing hover-only). The reason is written, with an icon: "Mac non connecté".
- The "Connecter un Mac" link is a real link to the Mac section of the settings (screen 3). It stays focusable even though the radio is disabled. If Apple mode is off on the server, the reason reads "Mode Apple désactivé sur ce serveur" and there is no link.
- Loading: while the Mac state loads, the radio is disabled with "Vérification du Mac…".
- Error (state cannot be loaded): "Impossible de vérifier le Mac. Réessayer" (button), the radio stays disabled.
- Creation refused by the server (`platform=apple` without a Mac): the error is shown above the submit button, `role="alert"`, with the same link.
- Once chosen, "Apple – Swift" shows an info line: "Le projet devra contenir un fichier .palabre/apple.toml."

## 3. Mac builder state (settings)

Section "Mac de build" in the settings.

```
Mac de build
● Connecté   · build-mac-1 · vu il y a 12 s
  VM en cours : 1 / 2 · File d'attente : 0
  [Révoquer ce Mac]

○ Hors ligne · build-mac-1 · vu il y a 3 h
  Les builds Swift restent en attente tant que le Mac est hors ligne.
  [Générer un code de connexion]
```

- Two states, each with an icon and a text: "Connecté" (filled dot ● + text) and "Hors ligne" (empty dot ○ + text). Last-seen is relative time with the full date in a `title`/`<time datetime>`.
- Connected: name, VMs running over the maximum ("1 / 2"), queue length, all as text.
- Offline: the consequence is written. The state is also announced in the live region: "Le Mac est hors ligne".
- No Mac enrolled (empty state): "Aucun Mac connecté. Un Mac Apple silicon dédié compile et teste les projets Swift." and the button "Générer un code de connexion".
- "Générer un code de connexion" opens a dialog showing the one-time code once, with its lifetime ("valable 10 minutes", from the API), a "Copier" button ("Copié" announced in the live region) and the instruction to enter it on the Mac. Focus goes into the dialog, `Escape` closes it, focus returns to the button.
- "Révoquer ce Mac" asks a confirmation ("Révoquer build-mac-1 ? Il ne pourra plus recevoir de builds.") with "Révoquer" and "Annuler"; cancel is focused by default.
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
| `queued` | En attente · position n | ⏳ | If the Mac is offline: "En attente : le Mac est hors ligne" |
| `running` | En cours | spinner | Spinner is replaced by text with reduced motion |
| `passed` | Réussi | ✔ | Duration |
| `failed` | Échoué | ✖ | Counts of errors and failed tests |
| `error` | Erreur d'infrastructure | ⚠ | States it is not a code problem, "Relancer" |
| `timeout` | Délai dépassé | ⚠ | Duration limit reached, "Relancer" |
| `cancelled` | Annulé | ⊘ | |

- The commit (short SHA) is always shown. A result for an old commit is labeled "Ancien commit" and never shown as the current verdict.
- "Voir le détail" is a disclosure button (`aria-expanded`): build errors and warnings, then failed tests (name, message, `file:line`), then the log tail. Everything is plain text in a monospace block, scrollable and focusable (`tabindex="0"`) with a label "Journal de build".
- Screenshots (optional): a list of images with an `alt` such as "Capture d'écran 1 sur 3" and a link to the full size. Not shown if there is none.
- Loading: "Chargement du build…". Empty (no job yet): "Aucun build pour l'instant". Error: "Impossible de charger le build. Réessayer". Log not available (retention elapsed): "Journal supprimé après n jours".
- The status change is announced in the live region ("Build réussi", "Build échoué").
- Under 640px: the line wraps, the detail takes the full width.

## 5. Acceptance checklist

- Texts and error states of the three screens are written above.
- Contrast, labels, and no information carried by color alone are specified.
- To be validated by Chloé before development.
