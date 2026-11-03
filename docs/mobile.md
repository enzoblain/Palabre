# Mobile app

Architecture of the Palabre mobile app: iPhone first, Android from the same code, a near clone of iMessage
in look and behavior. This page is the plan the dev tasks follow; the screens come from the user stories and the
UI spec of the mobile tasks, not from here (see the [v1 user stories](mobile-stories.md)). The web app ([Use the apps](use-the-apps.md)) stays as it is.

## Decisions

| Topic | Choice | Why |
| --- | --- | --- |
| Framework | Expo (React Native), managed workflow | One code base for iOS and Android, builds without a local Xcode project, the team already writes React and TypeScript. |
| Expo SDK | The latest stable SDK on the day the app is scaffolded, pinned exactly in `package.json` (`expo`, `react-native`) | Expo ties each SDK to one React Native version; mixing them breaks native modules. Upgrading is a deliberate task per SDK, never a Dependabot major (see [Dependencies](dependencies.md)). |
| Language | TypeScript in strict mode, no `any` | Same rule as the web app. |
| Navigation | `expo-router` (file-based) | Standard with Expo, native stack and tab navigators, deep links for free. |
| Location | `mobile/` at the repo root, next to `backend/` and `frontend/` | Same release train and same PR flow; the web `frontend/` is not a workspace member, the two apps do not import each other's build. |
| Server state | Plain `fetch` plus a small hook layer (no query library at first) | The web app does the same with `api.ts`; add a library only if the polling code grows. |
| Storage of secrets | `expo-secure-store` (iOS Keychain, Android Keystore) | The web app uses `sessionStorage`, which does not exist on a phone. |

## Layout of `mobile/`

```
mobile/
  app/              expo-router screens (conversation list, conversation, project info, team, settings, login)
  src/api/          typed client, ported from frontend/src/api.ts
  src/components/   bubbles, composer, list rows, typing dots
  src/i18n/         same keys as the web app
  app.json          name, bundle id, version, permissions
  package.json      its own lockfile and its own `npm run check`
```

`npm run check` in `mobile/` runs the type check (`tsc --noEmit`), the tests and an i18n key check, like the
web app. CI gets one job for it that skips while `mobile/` does not exist, like the other jobs of `ci.yml`.

## Sharing code with the web app

The API client (`frontend/src/api.ts`) mixes pure parts (types, `ApiError`, `ERROR_CODES`, error mapping) with
browser parts (`sessionStorage`, `localStorage`, `translate`). Two options:

1. Copy the file into `mobile/src/api/` and swap the storage and translation for the phone's.
2. Extract the pure parts into a shared package and import it from both apps.

Recommended: start with a **copy** (option 1), with a test that fails when the copied `ERROR_CODES` and types drift
from `frontend/src/api.ts`, the same idea as the existing `ERROR_CODES`/`ErrorCode` backend test. The two apps ship
on different cycles (the phone one is gated by the App Store), and a shared package means a workspace, Metro
configuration and a second build path for the web Dockerfile. Revisit once the client is stable; then the pure
types are the first thing to extract.

## Connecting to the backend

### Server URL

The user types the server address on first launch (for example `https://palabre.example.com`) and it is kept in
secure storage. It must be **HTTPS**: iOS blocks clear HTTP (App Transport Security) and Android blocks it by
default from API 28, and the token must never cross a network in clear text anyway. A phone cannot reach
`127.0.0.1`, so the user needs the setup described in [Remote access](remote-access.md): a TLS reverse proxy
or a private network such as Tailscale. The app talks to the same `/api` as the web app, through the TLS proxy
on `2810` only: the backend port `2710` is never reached directly.

The browser rules (CORS) do not apply to a native app: `cors_origins` needs no change.

### Authentication

Each phone gets its own long-lived, revocable device session (`/api/auth/devices`), separate from the 12-hour web session (`POST /api/auth/session`, unchanged):

1. The user enters the server URL and the `ADMIN_TOKEN` (the access code) once.
2. The app pairs with `POST /api/auth/devices` (`Authorization: Bearer <ADMIN_TOKEN>`, body `{"name": "<device name>"}`, 1 to 100 characters). It answers `201` with `id`, `name`, `created_at`, `last_used_at`, `expires_at` and `token`, an opaque `pdev_...` string returned this once only.
3. Only the device token is stored (secure storage). The `ADMIN_TOKEN` is dropped from memory right after and never written to disk.
4. The token is sent as a bearer token like any session token. Its expiry slides: `DEVICE_SESSION_TTL_SECONDS` (30 days by default) counted from the last use, written at most once a minute per device although the app polls every 2 s.
5. On a `401` (revoked, expired or unknown token) the app clears the session and goes back to the login screen, like `onUnauthorized` on the web.

Management, behind a valid session (a device token or the web session): `GET /api/auth/devices` lists the devices (`id`, `name`, `created_at`, `last_used_at`, `expires_at`, never a token) and `DELETE /api/auth/devices/{id}` revokes one (`204`, `404` with `device_not_found` if unknown). Pairing needs the raw `ADMIN_TOKEN`: a session or device token cannot pair a new device.

Security: the database stores only an HMAC-SHA256 of the token, keyed by a key derived from the `ADMIN_TOKEN`, so changing the `ADMIN_TOKEN` revokes every phone. A wrong token, at pairing or later, feeds the same per-IP failure counter as the rest of the API (`429` once locked). The database is read only for tokens starting with `pdev_`.

Out of scope for v1: pairing by QR code or one-time code, push tokens, the web screen to revoke devices (separate task).

### Real time

The backend has no WebSocket or server-sent events. The web app polls (`ConversationView` every 2 seconds with
`listMessages(conversationId, sinceId)`, which returns only the new messages; the conversation list carries
`unread_count`, `lead_writing` and the last direction message). The app does the same:

- Conversation open and app in the foreground: poll messages every 2 s with `sinceId`.
- Conversation list in the foreground: poll `GET /projects` at a slower rhythm (about 5 s) for unread counts and the
  typing indicator.
- App in the background: stop polling, refresh once on return to the foreground (`AppState`).

Polling cannot notify a user whose app is closed. That is the main gap for an iMessage-like app. **Push
notifications** need backend work: a device-token table, an endpoint to register it, and a send step (Expo push
service, which wraps APNs and FCM) triggered when the lead writes in `direction`. This is a separate task, after
the app works with polling. A WebSocket or SSE endpoint is not needed for v1.

## Build and release

Step-by-step guide, secrets and rollback: [Mobile release](mobile-release.md). The sketch:

- **Tooling**: decided by the CEO: build on **GitHub-hosted runners**, upload to TestFlight, **no EAS** (no paid
  third-party service holding our certificates). iOS builds on a macOS runner (`npx expo prebuild`, then
  `xcodebuild archive`); Android on a Linux runner (Gradle, an `.aab`). Signing material stays in our own GitHub
  secrets.
- **Triggers**: only a push of a `vX.Y.Z` tag or `workflow_dispatch`; never `pull_request`. The ordinary CI only
  runs `npm run check`.
- **iOS**: archive, sign, upload to **TestFlight** with `xcrun altool` and an App Store Connect API key only (no
  fastlane). The App Store submission itself is done by hand by Enzo.
- **Versions**: the marketing version follows the release version (`X.Y.Z`); the build number is the run number.
  `release.py` must bump `mobile/app.json` (and `package.json`) with the other version files: a backend task.
- **Pins**: runner image (`macos-15` or the current stable one), Node 22 as everywhere, Expo and Xcode versions
  fixed, third-party actions pinned by SHA like the existing workflows, `permissions: contents: read` at the
  workflow level.

### Signing conditions (Security)

- Secrets (distribution certificate `.p12` and its password, provisioning profile, App Store Connect API key) live
  in a **protected GitHub environment** limited to `v*` tags, with required reviewers.
- The job that signs is never triggered by `pull_request` and never runs code from a fork.
- The certificate is imported into a **temporary keychain** created in the job; the keychain is deleted in a final
  step with `if: always()` so it goes away even when the build fails.
- Nothing secret in the logs (no `set -x` around the import, no echo of the profile).
- Android: the upload keystore is a secret of the same environment, decoded to a temporary file removed at the end.

Prerequisite: a **paid Apple Developer account**. Without it only an unsigned simulator build can be checked, and
TestFlight is impossible. This is a blocking question for the CEO (open question 137).

### Forbidden

- `AsyncStorage` for tokens: `expo-secure-store` only.
- App Transport Security exceptions and clear-text HTTP, on iOS and Android.
- `any` in TypeScript.

## Task breakdown

1. Scaffold `mobile/` (Expo, strict TypeScript, expo-router, `npm run check`, CI job, `docs/develop.md` entry). Front.
2. Typed API client port and the drift test; secure storage of the connection. Front.
3. Login screen: server URL, token, session, `401` handling. Front. Depends on 1 and 2.
4. Conversation list with unread counts and the typing indicator (polling). Front.
5. Conversation: bubbles, composer, sending with retry, polling with `sinceId`. Front.
6. Project info, team, settings and project creation screens. Front, one task per screen.
7. DevOps: iOS (TestFlight) and Android workflows, secrets environment, versions. DevOps, with Security review.
8. Release bump of the mobile version files in `release.py`. Backend.
9. Device sessions or pairing (longer-lived, revocable token). Backend, then front.
10. Push notifications: device registration, sending, then the app side. Backend, then front.

Tasks 1 to 6 give a usable app with polling; 7 can start as soon as 1 is merged; 8 to 10 are independent of the
screens.

## Open questions

- Paid Apple Developer account (question 137): who holds it and who can create the certificates (CEO).
- Pairing flow versus a longer session (backend developers, Security).
- Name and bundle identifier of the app (CEO).
