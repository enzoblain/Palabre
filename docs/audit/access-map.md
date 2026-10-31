# Access map: who reaches what, with which rights

Read-only map of `dev` (0.18.0 plus the egress, Anthropic proxy and loopback-bind fixes merged since). It complements [security.md](security.md), the list of findings. Risks carry a severity and a fix; "Fixed" ones are kept so the history stays readable.

## Actors and credentials

- **Boss (browser or Tauri app)**: `ADMIN_TOKEN`, one static bearer giving the full REST API (`api/deps.py`, `main.py`). Stored in `localStorage` by the frontend (`api.ts`). Clear HTTP unless the operator adds a TLS reverse proxy.
- **Backend process** (uid `palabre`, non-dumpable through `hardening.make_non_dumpable`): holds `GITHUB_TOKEN`, every `CLAUDE_CODE_OAUTH_TOKENS` entry, `POSTGRES_PASSWORD` and `ADMIN_TOKEN`. The entrypoint copies the Docker secrets to `/run/palabre-secrets` (0400) and closes `/run/secrets`.
- **Agent run** (uid `agentN` from a pool, one live run per uid): allowlisted environment, a per-run MCP bearer (`run_tokens.py`, revoked in `finally`, config file deleted at first use) and a run-scoped Claude token. The real Claude OAuth token stays in the backend and is added by the Anthropic proxy. Fresh `HOME`/`TMPDIR` per run, its own clone claimed 0700 (`palabre-claim-clone`) and taken back after the run.
- **GitHub**: only the backend talks to it, with a fine-grained token (contents and pull requests read/write, checks and metadata read, no `workflows` scope). Agents push nothing: the backend fetches the task clone through `palabre-upload-pack` and pushes itself.
- **CI (GitHub Actions)**: runs agent-written code on every push with `contents: read` (plus `packages: read` for compose). No repository secret beyond `GITHUB_TOKEN`.

## Flows

1. Boss to nginx `:2810` to backend `/api` (`ADMIN_TOKEN`). The desktop app reaches the backend `:2710` directly, which exposes `/api` and `/mcp`. Both ports are published on `127.0.0.1` by default (`PALABRE_BIND`, `PALABRE_WEB_BIND`).
2. Orchestrator to `sudo -u agentN claude -p`. The sudoers rules only allow the `claude` binary, `kill`, `rm-clone`, `upload-pack` and `claim-clone`.
3. Agent to `/mcp` on `127.0.0.1:8000`: the per-run token and the scope headers are checked server-side (`mcp_server/auth.py`), and tools are filtered by role server-side (`server.py`, `permissions.py`).
4. Agent Bash (roles with `code` or `run_tests`: developers, devops, QA, reviewer, security) to the network: `iptables` owner rules only allow `127.0.0.1:8000` (MCP) and the egress proxy `127.0.0.1:3128`, which opens port 443 of an allowlist of package registries to public addresses only. Postgres is unreachable.
5. Agent to the Anthropic API: only through the local proxy (`/anthropic`), which swaps the run token for the account's real token and only relays `POST v1/messages` and `v1/messages/count_tokens`. Server tools other than `web_search`, `mcp_servers`, `url`/`file` content sources and duplicate JSON keys are refused.
6. Research agents read web pages through the `fetch_page` MCP tool, run by the backend (https on 443, redirects re-checked, never to a non-public address).
7. Backend to the GitHub API and git over HTTPS with `GITHUB_TOKEN`; git children get a scrubbed environment and hooks, `fsmonitor` and protocols are neutralized on agent clones (`github.py`).
8. Backend to Postgres (`db:5432`, password from the secret file).

## Residual risks

| # | Severity | Status | Risk | Fix |
|---|----------|--------|------|-----|
| R1 | High | Fixed (#295, PR #263; Anthropic proxy #301/#306) | No egress control: a prompt-injected agent with Bash could exfiltrate the repo and its own Claude token | Egress proxy plus `iptables` owner rules; real token kept server-side. Known leftover: `npm publish` with an attacker-supplied npm token through `registry.npmjs.org` (accepted) |
| R2 | Medium | Fixed (PR #265, #267, #269) | Ports published on `0.0.0.0`: `/api` and `/mcp` in clear HTTP on the LAN | Bound to `127.0.0.1` by default, TLS reverse proxy documented (README, Remote access) |
| R3 | Medium | Open | `ADMIN_TOKEN` is a single static, all-powers credential, in `localStorage`, with no expiry. Rotation is documented, revocation means editing `.env` | Short-lived session token issued from `ADMIN_TOKEN` (HttpOnly cookie or memory). Inès judges documented rotation enough for now. M |
| R4 | Medium | Fixed (PR #263) | Agents with Bash could reach Postgres and the backend `/api` | `iptables` owner rules; `check-isolation.sh` verifies the database is unreachable |
| R5 | Low | Accepted | Agent code runs in CI on every branch push (`contents: read`) | Keep workflows free of secrets on push events and the token without `workflows` scope (`sensitive_paths` covers `.github/`) |
| R6 | Low | Open | A Claude OAuth token is per account, shared by several employees: one leak exposes all of them | One token per account, rotated through `claude setup-token`. Mitigated by R1 |
| R7 | Info | Accepted | Per-run MCP tokens live in memory only: a backend restart kills the runs | Documented in `run_tokens.py` |
| R8 | Low | Accepted | Bash has no command allowlist (`code`, `run_tests`): read-only roles can still write in their clone | Desk thrown away at each wake-up and nothing pushed from it. A `Bash(pytest:*)` allowlist would be brittle, not recommended |
| R9 | Medium | Open | No CSP or security headers in `frontend/nginx.conf` while the admin token is in `localStorage` (Tauri CSP done in PR #264) | Strict CSP and headers in nginx, see `frontend-ux.md` point 2. S |
| R10 | Low | Open | The 429 lockout is per IP: an agent could fail 10 times from `127.0.0.1` and lock out everything coming from the same IP | Agents no longer reach `/api` since R1 and R4; Inès re-checks it in review |
| R11 | Low | Fixed (#296, PR #262) | Stale desk folders left group-writable | Deleted at startup |

Backend git hardening is fine: a clone cannot trap the backend. `npm`/`pip install` runs third-party scripts under the agent uid, which is covered by R1.
