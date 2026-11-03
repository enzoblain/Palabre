# Security

- Security review is not self-declared: in the modes with a security gate, a pull request
  that changes a path listed in `backend/app/sensitive_paths.py` (dependency manifests and
  lockfiles, Dockerfiles, entrypoints, sudoers, `runner.py`, `config.py`, `mcp_server/`,
  scripts, secrets and CI files) needs security's approval, whatever the author flags. The
  files come from the pushed branch; the author's flag can only add the gate.
- The GitHub token never reaches the agents: the server pushes, opens pull requests and
  merges for them. Agents only get the environment variables they need, and their own
  Claude token.
- Secrets (`ADMIN_TOKEN`, `GITHUB_TOKEN`, `CLAUDE_CODE_OAUTH_TOKENS`, the database password)
  are Docker secrets, files and not environment variables: the container's environment holds
  none, so the healthcheck and every child process (git, `claude`) start without them. The
  entrypoint closes `/run/secrets` and gives the server a private copy in
  `/run/palabre-secrets` (read by `pydantic-settings`' `secrets_dir`).
- Agents have no free network. The entrypoint (root, `NET_ADMIN` from the compose file, dropped from the
  server's capabilities right after) adds `iptables` rules that only let the agents' uids connect to
  `127.0.0.1:8000` (MCP) and to the egress proxy (`127.0.0.1:3128`, `app/egress_proxy.py`, an HTTP `CONNECT`
  tunnel in the server). The proxy only opens port 443 of the hosts in `EGRESS_ALLOWED_HOSTS` (the npm, PyPI and Go
  registries by default, not the Anthropic API; set a JSON list to change it) and never to a non-public
  address. So an agent cannot send its Claude token elsewhere, and cannot reach `db:5432`. Runs get
  `HTTPS_PROXY` in their environment. If the capability is missing the container refuses to start;
  `EGRESS_FILTER=off` opts out. `check-isolation.sh` checks the database and Internet are unreachable.
  Consequences and residual risk: `WebFetch` is run client-side by Claude Code, so it is not available to the
  agents (`WebSearch` is served by Anthropic and still works).
  The proxy caps concurrent tunnels
  (`EGRESS_MAX_TUNNELS`). The Anthropic API is reached through a local reverse proxy
  (`app/anthropic_proxy.py`, `/anthropic` on the server, `ANTHROPIC_BASE_URL`): the agent's
  `CLAUDE_CODE_OAUTH_TOKEN` is only its run token (worthless outside the run), the server adds the account's real
  token, so it is in neither the agent's environment nor `/proc/<pid>/environ`, and cannot be sent to the API with a
  server-side tool. The proxy also refuses server tools other than `web_search` (`ANTHROPIC_ALLOWED_SERVER_TOOLS`,
  so no `web_fetch` or `code_execution`), `mcp_servers`, content blocks whose `source` is a `url` or a `file` (Anthropic would fetch it server-side,
  a way around the allowlist; Claude Code only sends base64), and API paths outside `ANTHROPIC_ALLOWED_PATHS`.
  Paths are matched exactly (`v1/messages`, `v1/messages/count_tokens`): no batches, no OAuth endpoints.
  A CONNECT proxy cannot filter by method, so `registry.npmjs.org` still allows an `npm publish`
  with an attacker-supplied npm token: a known, accepted risk.
- Agents run as other system users. The server runs as `palabre` (uid 1000); each `claude`
  process is started as an `agent` account (`agent1..N` with the pool) through one `sudo` rule that only allows the
  `claude` binary, so an agent cannot read the server's environment, `/proc/<pid>/environ`,
  database URL or tokens. In `/data`, only the server can read the project's reference
  clone and `runtime/`; agents write in their task and desk clones, Claude's sessions and
  the Go cache, and only read the toolchains. The server's `PATH` never includes the
  toolchains. Do not add `no-new-privileges` to the compose file: `sudo` needs it off.
  Every run is `sudo -n -u agent` with a fixed list of variables (`HOME`, `PATH` with the
  toolchains, `CLAUDE_CONFIG_DIR`, the account's token, git identity, `safe.directory` set to the run's
  own clone), never inherited from the
  server. Secrets travel in that environment, not in the command line, so `ps` does not show
  them; the run's MCP config is a file in `/data/run`, which agents can cross but not list.
  A second `sudo` rule only lets the server kill a process group of the agent, to stop a run
  that timed out. A third one runs `palabre-rm-clone`, a root-owned script that, as `agent`, only
  empties a desk or task clone (files the agent made outside the shared group, which the
  server cannot remove itself; the server then removes the empty directory). With `AGENT_USER` empty, none of this applies.
  Publishing a task branch (`push_task_branch`) fetches it from the agent's clone through `palabre-upload-pack`, a fifth `sudo` rule (root-owned script, an exact task clone path only) that runs `git upload-pack` as the account owning the clone: whatever the agent puts in its `.git` (alternates, `commondir`, symlinks), the OS refuses it another project's objects. The server fails closed, with an explicit error, if the clone is no longer owned by a pool account (taken back) or if `sudo` or the script is missing. The fetch into the reference runs with `transfer.fsckObjects`, so a malformed pack never reaches GitHub, and the indirection denylist stays as defence in depth. In the legacy shared-account mode (no pool), the clones stay palabre's and the upload-pack runs as the shared `agent` account, which only reads what that account can already read.
  Each live run's clone and Go cache (`/data/toolchains/gopath/employee-<id>`) are handed to its account just before it starts, by `palabre-claim-clone` (root-owned, run through a fourth `sudo` rule that only accepts a clone path and an `agentN` or `palabre` account): owner and group become the account and its private group, so no other run can write a hook, a git config or a Go module there for someone else's run to execute (#160). A task clone is therefore writable by one run at a time: once the run's processes are killed (and only then), the clone and the Go cache go back to `palabre` before the account serves another employee, and the server also takes them back at every start. The claim refuses a tree holding a file of another account or a hard link to a file outside the clone; hard links that stay inside the clone (`npm install` makes some) are replaced by copies of the same content and permission bits, made as the account itself once the tree is handed over (never as root, so no swapped name can steer a privileged write). The script walks the tree with `chown -R -h` / `chmod -R`, which never follow a symlink. If the hand-back fails, the account stays out of the pool until restart. The projects root of the three root-owned scripts and of their `sudo` rules is the `PROJECTS_DIR` build argument (default `/data/projects`), written to `/etc/palabre/projects-root.conf` at build; a script refuses everything if that file is missing or the root is empty, `/`, relative or has odd characters, and the build fails on such a value. The build and the entrypoint also require a root strictly under `/data/` that is none of `/data/run`, `/data/runtime`, `/data/claude`, `/data/toolchains` (or below them), since the entrypoint chowns it as root; an explicitly empty runtime `PROJECTS_DIR` is refused too. `check-isolation.sh` reads the same file. The strict validation of the root lives in the build and in the entrypoint; the root scripts only read the configuration they validated. Without a pool (`AGENT_POOL_SIZE=0`, shared `AGENT_USER`) nothing is claimed: at every start the entrypoint instead gives the clones and Go caches to the group `work` (group-writable, setgid), so the one agent account can still write in them and serve them to `palabre-upload-pack` after a restart. Clones are only taken back to `palabre:palabre` go-rwx with a pool.
  Each live run also gets its own account (`agent1..agentN`, `AGENT_POOL_SIZE`), with a private group the server belongs to: the run's MCP config and Claude config dir are readable by that group only, so another run can read neither the environment nor the config of a live run. Runs beyond the pool size wait for a free account.
  Clones are made with `--no-hardlinks`, so they share no object with the reference (whose
  objects stay private). Desks are recloned at every run and fix themselves. A task clone made
  before this fix still holds hard links: once its work is pushed, delete
  `/data/projects/<id>/worktrees/task-<n>` (as the server user) and it is recreated on the
  agent's next start.
  Claude's sessions are not shared: `/data/claude` (`CLAUDE_STORE_DIR`) is the server's own store (mode 700), with one
  directory per employee. Each run gets a throwaway `CLAUDE_CONFIG_DIR` in `/data/run` holding
  only the session it resumes, and the server copies back the sessions it wrote (regular files
  only) and deletes the directory. A `settings.json` or hook an agent writes there dies with
  the run and never reaches another employee's. Sessions of a volume made before this change
  are purged at the first start (agents begin a new session).
  Known limit: the isolation holds between runs only with the pool (`AGENT_POOL_SIZE` above 0); in the shared-account mode all
  runs share one uid and can read each other's processes, tokens and sessions.
  To check an image, see [Checking the isolation](#checking-the-isolation).
  Agents still share the container's network (limited by the egress firewall), so keep Postgres' password strong.
- Each run gets its own random MCP token, held in server memory: it is revoked when the
  run ends, and the `--mcp-config` file holding it is deleted on the first MCP request.
  A token stolen from another run (`ps`, the config file) stops working once that run is
  over. The token is tied to the run and to its task or conversation (the headers must match
  the scope recorded at start), not to one MCP session: `claude` reopens sessions during a
  run, so each `MCP initialize` is only logged by the backend. With the pool, each run has its own uid, so another run cannot read the token;
  in the shared-account mode it still could while the run is live.
- Each agent's tools come from its role. Merge rules are enforced by the server, not by
  the agents' good will.
- The API is protected by `ADMIN_TOKEN`. The server port is published on `127.0.0.1` only;
  for remote access use a TLS reverse proxy or a private network ([Remote access](remote-access.md)): Palabre is not meant to be exposed to the internet.

## Checking the isolation

The Compose smoke test in CI runs the agent pool isolation check and
`check-migration.sh` on the image it builds, and fails on any `FAIL`; the log shows each `ok`
line and a final count. The task flow check needs a scratch GitHub repository, so it stays
manual, as does running either script on another image after changing the Dockerfile, the
entrypoint or the runner. Two scripts in `backend/scripts/`:

```sh
# 1. Migration of a volume made before the agent user (needs Docker on the host only; also run by the CI)
backend/scripts/check-migration.sh <image>

# 2. Agent runs and task flow, in a throwaway container with a scratch GitHub repository
#    (the token only needs to push to it: the check opens a PR there and merges it)
printf %s "$GITHUB_TOKEN" > /tmp/github_token
docker run -d --name palabre-check -v palabre-check-data:/data \
  -v /tmp/github_token:/run/secrets/github_token:ro <image> sleep infinity
docker exec -u root -e CHECK_GITHUB_REPO=owner/scratch-repo palabre-check /srv/scripts/check-isolation.sh
docker rm -f palabre-check && docker volume rm palabre-check-data
```

The second script swaps `claude` for a stub while it runs (use a throwaway container, never
one whose orchestrator is running agents), so no Claude account is needed. It checks that a
run is `uid agent` through `sudo -u` with the right `PATH`; that the agent cannot read the
backend's `environ`, the project reference, `/data/runtime` or the secret files; that a run
past its timeout leaves no agent process; that `sudo` has `!use_pty`; and, with
`CHECK_GITHUB_REPO`, the whole task flow (clone, commit by the agent, push from the
reference, PR, merge). Without `CHECK_GITHUB_REPO` the flow is skipped and the exit code is
non-zero. Every line is `ok` or `FAIL`.
