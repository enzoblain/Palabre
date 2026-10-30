# Security audit

Read-only audit of `dev` (2026-10-30). Findings sorted by severity, each with location, impact, fix and effort (S/M/L). No code was changed.

## High

### H1. Shared `agent` uid exposes other runs' secrets
- Where: `backend/app/runner.py:98`, `runner.py:194`.
- Impact: every run executes as the same uid, so any agent with Bash can read `/proc/<pid>/environ` and `cmdline` of the other live runs: `CLAUDE_CODE_OAUTH_TOKEN` of other Claude accounts and the live MCP token of the lead. With the lead's token, an agent can merge or release without review. Per-run tokens, scope and revoke (#108, #119, #131) shrink the window to the lifetime of the run, they do not close it.
- Fix: one uid per run, or at least a dedicated uid for the lead. Effort: L.

### H2. `/data/claude` is shared and writable by all agents
- Where: `entrypoint.sh:28` (mode 2775), `CLAUDE_CONFIG_DIR` in the `Dockerfile`.
- Impact: an agent with Bash can edit the lead's session `.jsonl` files (resumed with `--resume`) or `settings.json` (hooks), i.e. persistent prompt injection or command execution in another employee's next run.
- Fix: one `CLAUDE_CONFIG_DIR` per employee, not writable by the others. Effort: M/L.

## Medium

### M1. The `sensitive` flag is self-declared
- Where: `backend/app/workflow.py:394`, `workflow.py:515`.
- Impact: the developer decides whether their PR goes through security; a dev can skip the security gate.
- Fix: detect sensitivity from the changed paths (auth, dependency manifests and lockfiles, `Dockerfile`, `entrypoint.sh`, sudoers, `runner.py`, `mcp_server/`), the flag can only add, never remove. Effort: S/M.

### M2. `ADMIN_TOKEN` has no minimum length, no rate limit
- Where: `backend/app/config.py:91-97`.
- Impact: a short token can be brute-forced over the network.
- Fix: minimum 32 characters (same for `POSTGRES_PASSWORD`), basic rate limit on failed auth. Effort: S.

### M3. Unpinned supply chain
- Where: `Dockerfile:54` (`curl | bash` install of Claude Code, unpinned), compose `:19`, `:52` (`:latest` images + auto updater), compose `:67` (updater mounts `docker.sock`).
- Impact: a compromised upstream script or image is pulled and run automatically, with Docker socket access (= root on the host).
- Fix: pin the Claude Code version + checksum, pin images by digest, make updates explicit. Effort: S/M.

### M4. Admin token in `localStorage`, no CSP
- Where: `frontend/src/api.ts:192-207`, `nginx.conf`.
- Impact: any XSS (agent-written content is rendered in the UI) can steal the admin token.
- Fix: strict CSP and security headers in nginx (`default-src 'self'`, no inline script, `frame-ancestors 'none'`, `X-Content-Type-Options`). Effort: S.

## Low

- L1. API in clear HTTP on `0.0.0.0:2710` (compose `:43`, `Dockerfile:74`), `/mcp` exposed too. Fix: bind to `127.0.0.1` by default, document a TLS reverse proxy. S.
- L2. `cors_origins = ["*"]` (`config.py:35`). Fix: restrict to the app origins. S.
- L3. `compare_digest` on `str` with non-ASCII input raises → 500 (`api/deps.py:20`). Fix: compare encoded bytes. S.
- L4. Prompts passed in argv (`runner.py:199`, `runner.py:206`), visible in `ps` to every agent. Fix: pass them on stdin. S.
- L5. Remote images in Markdown (`Markdown.tsx`) allow pixel tracking / IP leak. Fix: block remote `img` or proxy them, CSP `img-src`. S.
- L6. Shared `GOPATH` between agents (same class as H2, lower impact). S.
- L7. Commit messages are injected into the lead's prompt (prompt injection, low). Fix: frame them as untrusted data, like CI output (#121). S.

## Note on the "second session" alert

No code path on `dev` posts this alert anymore (removed by #131 / PR 101). The instance that still shows it runs an image older than PR 101. The CHANGELOG does not mention PR 101, so we cannot tell which version contains it: worth fixing in the release notes.

## What is already fine

Secrets as files on tmpfs, explicit env allowlist for git and runs, sudoers limited to 3 rules, per-run MCP tokens with server-side scope and revoke in `finally`, react-markdown links filtered, hashed `requirements`.

## Suggested order

H2 and M1 first (cheap compared to their impact), then M2/M3/M4 (all S), then H1 (larger isolation work).
