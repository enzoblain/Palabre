# Install the server

You need a machine with Docker and Compose (amd64 or arm64), a Claude subscription and,
for software projects, a GitHub token.

```sh
mkdir palabre && cd palabre
curl -fsSLO https://raw.githubusercontent.com/enzoblain/Palabre/main/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/enzoblain/Palabre/main/.env.example -o .env
# Fill in .env (see [Configuration](configuration.md)), then:
docker compose pull
docker compose up -d
```

Four values in `.env` are required:

| Variable | What it is |
|---|---|
| `ADMIN_TOKEN` | Protects the API; the apps ask for it. At least 32 characters (startup fails otherwise), e.g. `openssl rand -hex 32`. After 10 failed attempts within 5 minutes, an IP gets `429` until the window passes |
| `CLAUDE_CODE_OAUTH_TOKENS` | Run `claude setup-token`. Several accounts: separate their tokens with `\|` |
| `GITHUB_TOKEN` | Fine-grained token on your repositories: Contents and Pull requests (read/write), Checks and Metadata (read) |
| `POSTGRES_PASSWORD` | At least 32 characters: letters, digits, `-` and `_` |

The server listens on port `2710`, bound to `127.0.0.1` by default (this machine only), and the web app on port `2810`.
See [Remote access](remote-access.md) to reach the server from another machine.

## Updates

Upgrading from a version before secret files: keep your `.env` as it is, the four secrets are
still read from it. Compose now mounts them as files (`/run/secrets`) instead of environment
variables, so you need Compose 2.30 or later, and any other variable you set must be one of
those listed in the first table of [Configuration](configuration.md): the container no longer gets the whole
`.env`, so settings like `CORS_ORIGINS`, `CLAUDE_MAX_TURNS`, `AGENT_TIMEOUT_S`,
`IDLE_MINUTES`, `MAX_REVIEW_ROUNDS` or `CI_MISSING_MINUTES` must now be added to the
`environment:` of the `backend` service in `docker-compose.yml`. Recreate the containers: `docker compose pull && docker compose up -d`. Nothing
else changes; Postgres keeps its current password.

Upgrading from a version that accepted short secrets: `ADMIN_TOKEN` and `POSTGRES_PASSWORD` must now
have at least 32 characters, or the backend refuses to start. Generate new values with
`openssl rand -hex 32`. For `ADMIN_TOKEN`, edit `.env` and run `docker compose up -d`. For
`POSTGRES_PASSWORD`, change it in Postgres first, because the database image only reads it when it
creates an empty volume: `docker compose exec db psql -U palabre -c "ALTER USER palabre WITH PASSWORD '<new>'"`,
then put the same value in `.env` and run `docker compose up -d`.

Upgrading from a version before the agent user: nothing to do. The container starts as
root, re-owns the existing `/data` volume once (group `work`, marker `/data/.isolation-v1`),
makes each project's reference clone private to the server, then drops to `palabre`. If
you run the image without Docker's entrypoint, do that `chown`/`chmod` yourself.
After dropping root, the entrypoint execs `tini`: PID 1 is tini running as `palabre`, and it
reaps the orphans of killed agent runs, so `docker run` without Compose needs no `--init`.

```sh
docker compose pull && docker compose up -d
```

Or let Palabre update itself: with `COMPOSE_PROFILES=autoupdate` in `.env`, an `updater`
container checks for a new version every 5 minutes and restarts the server and web app
when one is out. Running agents get 60 seconds to stop cleanly.

Automatic updates are a security trade-off. The `updater` mounts `/var/run/docker.sock`, which
is root on the host, and it only finds new images under a moving tag, so you also set
`PALABRE_VERSION=latest`: a compromised image or registry account would then run on your
machine without anyone choosing it. Leave it off (the default) unless you accept that; by
default every image is pinned (Palabre by version; `postgres`, `docker`, and the Python, Node and nginx bases by digest)
and you update on purpose with the command above.

Claude Code is installed in the image at the version pinned in `backend/Dockerfile`, after its
SHA-256 is checked against the pinned value (taken from Anthropic's release manifest, which is
fetched from the same host as the binary: it protects against drift and corruption, not against
a compromise of that host at the time of the bump). Anthropic does not publish an independent signature we check here.
To bump it, change `CLAUDE_CODE_VERSION` and both checksums together.
