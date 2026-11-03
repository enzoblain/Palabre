# Mobile app UI

UI spec of the [Mobile app](mobile.md), designed by Emma (UX/UI) from the stories in [Mobile stories](mobile-stories.md) and the v1 scope (bubbles, list, dark mode, device sign-in; no reactions, no photos). It follows the visual codes of iMessage and uses no Apple asset. User-facing strings are quoted in French, the app's default language. Values come from the spec as posted; nothing here is decided by the author of this file.

Light / dark values are written `light/dark`.

## Tokens

| Token | Value |
| --- | --- |
| Background | `#FFFFFF` / `#000000` |
| Secondary background | `#F2F2F7` / `#1C1C1E` |
| Text | `#000000` / `#FFFFFF` |
| Secondary text | `#6C6C70` / `#98989F` |
| Separator | `#C6C6C8` / `#38383A` |
| Sent bubble (boss) | `#0066E0` / `#0066E0`, white text |
| Link / accent (text links, unread dot) | `#0066E0` / `#4DA3FF` |
| Received bubble | `#E9E9EB` / `#26262A` |
| Error | `#D70015` / `#FF453A` |
| Success | `#17743A` / `#34C759` |

## Typography and measures

- System font (SF on iOS, Roboto on Android). Body 17, caption 12, large title 34 bold.
- Dynamic Type: system scale, no fixed height, capped at x2.0 on the list.
- Spacing scale: 4 / 8 / 12 / 16 / 24.
- Radii: bubble 18, input field 18, round avatar.
- Minimum touch target: 44x44.
- No Apple asset.

## Mapping Palabre to iMessage

| Palabre | iMessage equivalent |
| --- | --- |
| Room | Group conversation |
| DM with an agent | 1:1 conversation |
| Agent | Contact: round avatar 40, initials, stable color derived from the name |
| Boss | "Me": blue bubbles on the right |
| Agent message | Received bubble on the left; sender name in caption 12 above it (rooms only) |
| Boss request | Received bubble with a "Demande" banner; the answer goes through the input bar |
| Task | Card inside a received bubble: title + status as text and icon, never color alone |
| System message | Centered text, caption 12, gray |

## Sign-in screen

- Fields: "Adresse du serveur" (https required, URL keyboard) and "Jeton administrateur" (masked, eye button with an accessible label).
- Button "Se connecter": height 50, radius 14, blue.
- Token kept in secure storage, never shown again.
- Empty: empty fields, help text "Le jeton se trouve dans la configuration du serveur".
- Loading: button disabled with an indicator, "Connexion…".
- Errors: red, icon + text under the field:
  - "L'adresse doit commencer par https://"
  - "Serveur introuvable. Vérifie l'adresse et ta connexion."
  - "Jeton refusé. Vérifie-le dans les réglages du site."
- Revoked session: back to this screen with "Cet appareil a été déconnecté. Reconnecte-toi."

## Conversation list

- Large title "Messages", search at the top.
- Rows: minimum height 76. Avatar 48, name 17 bold, preview 2 lines 15 gray, time on the right 15 gray, blue dot 10 for unread (name in bold as well). Inset separator 76.
- Sorted by last activity. Pull to refresh. Polling paused in the background.
- Loading: 8 skeleton rows.
- Empty: "Aucune conversation. Les messages de l'équipe apparaîtront ici."
- Error: banner "Impossible de charger les conversations." + "Réessayer"; if a cache exists, the list stays under the banner.
- VoiceOver reads: name, preview, time, "non lu".

## Conversation screen

- Header: back "< Messages", avatar 32 + name centered, team status button on the right.
- Bubbles: padding 8/12, radius 18, max width 75 %, 2 gap inside a series, 8 between series, tail on the last bubble of a series.
- Timestamp centered (caption 12) when the gap is over 1 h.
- Auto-scroll to the bottom unless the user scrolled up (then a "Nouveaux messages" pill is shown).
- Loading: 5 alternating skeleton bubbles.
- Empty: "Aucun message. Écris le premier."
- Error: banner "Messages indisponibles" + "Réessayer".
- Implementation: the screen opens the project's direction room (first conversation); a sent message shows at once, a failed one stays with "Non envoyé. Touche pour réessayer." and a tap sends it again; a request from the lead carries a "Demande" label; new team messages are announced to VoiceOver. The tail is a smaller corner radius on the last bubble of a series.

## Input bar

- Multiline field (max 5 lines), secondary background, radius 18.
- Round send button 32, blue, with an arrow, label "Envoyer", disabled when empty.
- Sending: bubble at 60 % opacity.
- Failure: error icon + "Non envoyé. Touche pour réessayer."
- The bar follows the keyboard and respects the safe area.
- No photos and no reactions in v1.

## Team status

- Modal sheet opened from the conversation header: avatar, name, role, "Disponible" / "Occupé" (filled icon or ring + text).
- Loading: skeletons.
- Empty: "Aucun membre à afficher."
- Error: "Statut indisponible" + "Réessayer".
- Closing: swipe down or "Fermer" button.

## Accessibility

- AA contrast in both modes (4.5:1 for text, 3:1 for icons). Ratios below are computed with the WCAG relative luminance formula:

| Pair (light / dark) | Ratio |
| --- | --- |
| White text on sent bubble `#0066E0` | 5.3 / 5.3 |
| Link on background | 5.3 / 10.3 |
| Link on secondary background | 4.7 / 6.4 |
| Success on background | 5.8 / 9.5 |
| Success on received bubble (task card) | 4.8 / 6.8 |
| Error on background | 5.4 / 6.2 |
| Error on secondary background | 4.8 / 5.0 |
| Secondary text on background | 5.2 / 7.3 |
| Secondary text on secondary background | 4.7 / 5.9 |
| Blue dot and send button on background (icons) | 5.3 / 4.0 |

- Secondary text and error text must not be placed on the received bubble (below 4.5:1 there).
- User-facing strings go through the i18n layer from the start (`src/i18n`), never hardcoded.
- VoiceOver / TalkBack labels on every icon button, logical focus order, new messages announced as polite, reduced motion respected.
- Dynamic Type: see Typography and measures.

## Dark mode

Follows the system; no setting in v1. Token values are in the table above.

## Liquid Glass

Only on the header and the input bar under iOS 26. Fallback to a solid background (`#F2F2F7` / `#1C1C1E`) on Android, or when "Reduce Transparency" is on.
