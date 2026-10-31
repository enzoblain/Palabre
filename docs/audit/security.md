# Security audit

Audit of `dev`, first written 2026-10-30 and updated 2026-10-31. Findings sorted by severity, each with location, impact, fix and effort (S/M/L). Status: **Fixed** (merged), **Open**. The map of actors, credentials and flows, with the risks of the second audit (R1 to R11), is in [access-map.md](access-map.md).

## Fixed since the first audit

- H1. Shared `agent` uid: one uid per run from a pool, per-run tokens and `/proc` isolation. Verified in a container by `check-isolation.sh` and `check-migration.sh`, run by the "Compose smoke test" job of `ci.yml` (via `.github/scripts/compose-smoke.sh`), see #162 and #172.
- H2. Shared `/data/claude`: one Claude config directory per run. Verified by `test_run_config_dir_is_throwaway_and_sessions_stay_private` in `backend/tests/test_agent_isolation.py`, see #162 and #172.
- M5. `ADMIN_TOKEN` static and never expiring: fixed, the apps log in with it (`POST /api/auth/session`) and keep only a stateless HMAC session token (12 h by default, `SESSION_TTL_SECONDS`) in `sessionStorage`; changing the `ADMIN_TOKEN` revokes every session. The raw token still works for scripts. HttpOnly cookie left out for now.
- M2. `ADMIN_TOKEN` length and rate limit: fixed, 32 characters minimum (same for `POSTGRES_PASSWORD`), `429` after 10 failures in 5 minutes.
- M3. Unpinned supply chain: fixed, Claude Code pinned with checksums and images pinned.
- L3. `compare_digest` on non-ASCII input: fixed.
- L1. API in clear HTTP on `0.0.0.0`: fixed (PR #265, #267), bound to `127.0.0.1` by default, reverse proxy documented. This is R2 of the access map.
- L5. Remote images in Markdown: covered by the CSP (`img-src 'self' data:`).
- Egress and Claude token exfiltration (access-map R1, R4): fixed by #295 (PR #263), #301 (PR #268) and #306 (PR #271).
- M1. Self-declared `sensitive` flag: fixed (#151), sensitivity is detected from the changed paths (`backend/app/sensitive_paths.py`, `workflow.py:453`), the flag can only add.
- M4. No CSP in nginx: fixed (#127), strict CSP and security headers in `frontend/security-headers.conf`, included from `frontend/nginx.conf`. The long-lived admin token in `localStorage` is gone with M5 (access-map R3, R9).
- L2. `cors_origins = ["*"]`: fixed (#311), the default is the Vite dev server and the Tauri webview origins, overridable with `CORS_ORIGINS`.
- L4. Prompts passed in argv: fixed (#312), the prompt travels on stdin and the system prompt in a private file (`--append-system-prompt-file`), so `ps` shows neither.
- L7. Commit messages in the lead's `release_pending` prompt: fixed (#314), framed as untrusted data with the same helper as CI output (#121). The changelog entry returned by `merge_release` to the lead is built from the same messages and stays unframed: accepted, it is a tool result.
- L6. Shared `GOPATH`: fixed (#136, tested in #313), `GOPATH` and `GOMODCACHE` are per employee (`toolchains.gopath`), only the Go binary in `bin/` stays shared.
- Stale desk permissions: fixed by #296 (PR #262).

## Open: medium

None.

## Open: low

- L8. Claude OAuth tokens are shared by the employees of an account (access-map R6). Fix: one token per account rotated with `claude setup-token`; the egress filter already keeps agents away from `/api`. S.
- L9. `Bash` has no command allowlist, so read-only roles can write in their clone (access-map R8). Accepted: the desk is thrown away and nothing is pushed from it.
- L10. The 429 lockout is per IP (access-map R10). Behind a shared proxy one attacker locks everyone out. Fix: key the lockout on the forwarded client address. S.

## Note on the "second session" alert

No code path on `dev` posts this alert anymore (removed by #131 / PR 101). The instance that still shows it runs an image older than PR 101. The CHANGELOG does not mention PR 101, so we cannot tell which version contains it: worth fixing in the release notes.

## What is already fine

Secrets as files on tmpfs, explicit env allowlist for git and runs, sudoers limited to the `claude` binary and four helper commands, egress allowlist, Claude token kept server-side, per-run MCP tokens with server-side scope and revoke in `finally`, react-markdown links filtered, hashed `requirements`.

## Suggested order

M5 (access-map R3) first, then the low item L8.
