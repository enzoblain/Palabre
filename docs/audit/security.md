# Security audit

Audit of `dev`, first written 2026-10-30 and updated 2026-10-31. Findings sorted by severity, each with location, impact, fix and effort (S/M/L). Status: **Fixed** (merged), **Open**. The map of actors, credentials and flows, with the risks of the second audit (R1 to R11), is in [access-map.md](access-map.md).

## Fixed since the first audit

- H1. Shared `agent` uid: fixed, one uid per run from a pool, per-run tokens and `/proc` isolation checked by `check-isolation.sh`.
- H2. Shared `/data/claude`: fixed, one Claude config directory per run.
- M2. `ADMIN_TOKEN` length and rate limit: fixed, 32 characters minimum (same for `POSTGRES_PASSWORD`), `429` after 10 failures in 5 minutes.
- M3. Unpinned supply chain: fixed, Claude Code pinned with checksums and images pinned.
- L3. `compare_digest` on non-ASCII input: fixed.
- L1. API in clear HTTP on `0.0.0.0`: fixed (PR #265, #267), bound to `127.0.0.1` by default, reverse proxy documented. This is R2 of the access map.
- Egress and Claude token exfiltration (access-map R1, R4): fixed by #295 (PR #263), #301 (PR #268) and #306 (PR #271).
- M1. Self-declared `sensitive` flag: fixed (#151), sensitivity is detected from the changed paths (`backend/app/sensitive_paths.py`, `workflow.py:453`), the flag can only add.
- M4. No CSP in nginx: fixed (#127), strict CSP and security headers in `frontend/security-headers.conf`, included from `frontend/nginx.conf`. The admin token in `localStorage` remains, covered by M5 (access-map R3, R9).
- Stale desk permissions: fixed by #296 (PR #262).

## Open: medium

### M5. `ADMIN_TOKEN` is static and never expires
- Where: `backend/app/api/deps.py`, `frontend/src/api.ts` (access-map R3).
- Impact: one all-powers credential, no revocation other than editing `.env`. Rotation is documented in the README.
- Fix: short-lived session token issued from `ADMIN_TOKEN` (HttpOnly cookie or memory); Security thinks documented rotation is enough for now. No task yet. Effort: M.

## Open: low

- L2. `cors_origins = ["*"]` (`config.py:35`). Fix: restrict to the app origins. S.
- L4. Prompts passed in argv (`runner.py:199`, `runner.py:206`), visible in `ps` to every agent. Fix: pass them on stdin. S.
- L6. Shared `GOPATH` between agents (same class as the fixed H2, lower impact). S.
- L8. Claude OAuth tokens are shared by the employees of an account (access-map R6). Fix: one token per account rotated with `claude setup-token`; the egress filter already keeps agents away from `/api`. S.
- L10. The 429 lockout is per IP (access-map R10). Behind a shared proxy one attacker locks everyone out. Fix: key the lockout on the forwarded client address. S.
- L9. `Bash` has no command allowlist, so read-only roles can write in their clone (access-map R8). Accepted: the desk is thrown away and nothing is pushed from it.
- L7. Commit messages are injected into the lead's prompt (prompt injection, low). Fix: frame them as untrusted data, like CI output (#121). S.

## Note on the "second session" alert

No code path on `dev` posts this alert anymore (removed by #131 / PR 101). The instance that still shows it runs an image older than PR 101. The CHANGELOG does not mention PR 101, so we cannot tell which version contains it: worth fixing in the release notes.

## What is already fine

Secrets as files on tmpfs, explicit env allowlist for git and runs, sudoers limited to the `claude` binary and four helper commands, egress allowlist, Claude token kept server-side, per-run MCP tokens with server-side scope and revoke in `finally`, react-markdown links filtered, hashed `requirements`.

## Suggested order

M5 (access-map R3) first, then the low items L2, L4, L6, L7.
