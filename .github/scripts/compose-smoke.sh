#!/usr/bin/env bash
# Smoke test of the Docker Compose setup on a real stack (run by the "Compose smoke test" CI job).
# Needs docker with compose 2.30+, git with the release tags, and curl. Run it from the repo root.
#   1. secrets as files: the stack is healthy and no secret is in the container's environment
#   2. fail-fast: an empty required secret (ADMIN_TOKEN, POSTGRES_PASSWORD) stops the startup
#   3. updater: it recreates the backend when a new image shows up, secrets still resolved
#   4. upgrade: the last published release runs on a volume, the current code takes it over
set -euo pipefail

ROOT=$(pwd)
# The stack reads .env from the project directory (the updater mounts it): never overwrite a real one
if [ -e .env ] || [ -e docker-compose.override.yml ]; then
  echo "Refusing to run: .env or docker-compose.override.yml exists here and would be overwritten and deleted." >&2
  echo "Run it from a clean clone." >&2
  exit 1
fi
IMAGE=ghcr.io/enzoblain/palabre
export PALABRE_VERSION=ci
export PALABRE_PORT=${PALABRE_PORT:-12710}
export PALABRE_WEB_PORT=${PALABRE_WEB_PORT:-12810}
WORK=$(mktemp -d)

# Distinct, greppable values: a leak in any environment shows up as a match
SECRETS=(
  "ADMIN_TOKEN=smoke-admin-9f3a1c7e5b"
  "GITHUB_TOKEN=smoke-github-4d8e2a6b01"
  "CLAUDE_CODE_OAUTH_TOKENS=smoke-claude-7c1b3f9d22|smoke-claude-0a5e8d4c66"
  "POSTGRES_PASSWORD=smokepg5b2d9e7f31"
)

fail() { echo "FAIL: $*" >&2; exit 1; }
step() { echo; echo "=== $* ==="; }

write_env() { # write_env <file> [VAR=value overrides...]
  local file=$1; shift
  printf '%s\n' "${SECRETS[@]}" "PALABRE_VERSION=$PALABRE_VERSION" "PALABRE_PORT=$PALABRE_PORT" \
    "PALABRE_WEB_PORT=$PALABRE_WEB_PORT" > "$file"
  local o
  for o in "$@"; do
    sed -i "/^${o%%=*}=/d" "$file"
    echo "$o" >> "$file"
  done
}

cleanup() {
  local p
  for p in smoke-main smoke-empty smoke-upgrade; do
    docker compose -p "$p" --profile '*' down -v --remove-orphans >/dev/null 2>&1 || true
  done
  rm -f "$ROOT/.env" "$ROOT/docker-compose.override.yml"
  rm -rf "$WORK"
}
trap 'rc=$?; [ $rc -ne 0 ] && dump_logs; cleanup; exit $rc' EXIT

dump_logs() {
  local p
  for p in smoke-main smoke-empty smoke-upgrade; do
    echo "--- logs $p ---"
    docker compose -p "$p" --profile '*' logs --no-color --tail 40 2>&1 || true
  done
}

wait_health() { # wait_health <seconds>
  local i out
  for ((i = 0; i < $1; i++)); do
    out=$(curl -fsS "http://127.0.0.1:$PALABRE_PORT/health" 2>/dev/null || true)
    case $out in *'"ok"'*) return 0;; esac
    sleep 1
  done
  return 1
}

# No secret value in the container's configured env, in what `env` prints, nor in PID 1's environ
assert_no_secret_in_env() { # assert_no_secret_in_env <project>
  local p=$1 s name value dump
  dump=$(docker compose -p "$p" exec -T backend sh -c 'env; echo; cat /proc/1/environ | tr "\0" "\n"')
  dump+=$(docker inspect -f '{{json .Config.Env}}' "$(docker compose -p "$p" ps -q backend)")
  for s in "${SECRETS[@]}"; do
    name=${s%%=*}; value=${s#*=}
    # Tokens list: check each one
    while IFS= read -r v; do
      [ -n "$v" ] || continue
      grep -qF -- "$v" <<<"$dump" && fail "$name value found in the backend environment"
    done < <(tr '|' '\n' <<<"$value")
    grep -q "^$name=" <<<"$dump" && fail "variable $name is set in the backend environment"
  done
  echo "ok: no secret in the backend environment"
}

assert_secrets_resolved() { # assert_secrets_resolved <project>
  local p=$1 f
  for f in admin_token github_token claude_code_oauth_tokens postgres_password; do
    docker compose -p "$p" exec -T backend test -s "/run/palabre-secrets/$f" \
      || fail "/run/palabre-secrets/$f missing or empty"
  done
  # /run/secrets is closed to anything but root
  [ "$(docker compose -p "$p" exec -T backend stat -c %a /run/secrets)" = 700 ] \
    || fail "/run/secrets is not mode 700"
  docker compose -p "$p" exec -T -u agent backend true || fail "no agent user in the image"
  # The agents' uid must reach neither /run/secrets nor the backend's private copy
  ! docker compose -p "$p" exec -T -u agent backend cat /run/secrets/github_token >/dev/null 2>&1 \
    || fail "agent can read /run/secrets/github_token"
  ! docker compose -p "$p" exec -T -u agent backend ls /run/palabre-secrets >/dev/null 2>&1 \
    || fail "agent can list /run/palabre-secrets"
  echo "ok: secrets resolved as files, closed to the agent user"
}

# --- 1. Secrets as files, then 3. updater --------------------------------------------
step "Secrets as files"
cd "$ROOT"
write_env .env COMPOSE_PROFILES=autoupdate PALABRE_UPDATE_INTERVAL=5
# The updater runs `pull` on images that exist only locally here: never pull them
cat > docker-compose.override.yml <<'YML'
services:
  backend:
    pull_policy: never
  web:
    pull_policy: never
YML
export COMPOSE_PROJECT_NAME=smoke-main
docker compose build backend web
docker compose up -d --wait --wait-timeout 120 db backend web
wait_health 30 || fail "backend does not answer on /health"
assert_secrets_resolved smoke-main
assert_no_secret_in_env smoke-main
# The API must refuse a call without the admin token and accept it with
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PALABRE_PORT/api/catalog/modes")
[ "$code" = 401 ] || [ "$code" = 403 ] || fail "API without token answered $code"
curl -fsS -o /dev/null -H "Authorization: Bearer ${SECRETS[0]#*=}" "http://127.0.0.1:$PALABRE_PORT/api/catalog/modes" \
  || fail "API refuses the admin token read from the secret file"

step "Updater recreates the backend"
before=$(docker compose ps -q backend)
docker compose up -d updater
# A new image under the same tag, as a published release would be
printf 'FROM %s:%s\nLABEL smoke=updated\n' "$IMAGE" "$PALABRE_VERSION" | docker build -q -t "$IMAGE:$PALABRE_VERSION" -
for ((i = 0; i < 120; i++)); do
  after=$(docker compose ps -q backend)
  [ -n "$after" ] && [ "$after" != "$before" ] && break
  sleep 2
done
[ -n "$after" ] && [ "$after" != "$before" ] || fail "updater did not recreate the backend"
logs=$(docker compose logs updater 2>&1)
case $logs in *Updated*) ;; *) fail "updater did not report the update";; esac
case $logs in *"Update failed"*) fail "updater reported a failure";; esac
wait_health 90 || fail "backend unhealthy after the updater recreated it"
assert_secrets_resolved smoke-main
assert_no_secret_in_env smoke-main
docker compose --profile '*' down -v --remove-orphans
rm -f .env docker-compose.override.yml
unset COMPOSE_PROJECT_NAME

# --- 2. Fail-fast ---------------------------------------------------------------------
for var in ADMIN_TOKEN POSTGRES_PASSWORD; do
  case $var in
    ADMIN_TOKEN) reason='admin_token' ;;
    POSTGRES_PASSWORD) reason='POSTGRES_PASSWORD is empty or missing|Database is uninitialized and superuser password is not specified' ;;
  esac
  step "Empty $var stops the startup"
  write_env .env "$var="
  if docker compose -p smoke-empty up -d --wait --wait-timeout 60 db backend; then
    fail "the stack started with an empty $var"
  fi
  curl -fsS "http://127.0.0.1:$PALABRE_PORT/health" >/dev/null 2>&1 && fail "backend answers with an empty $var"
  # It must be the refusal of this secret, not an unrelated failure
  logs=$(docker compose -p smoke-empty logs --no-color 2>&1 || true)
  grep -qiE "$reason" <<<"$logs" || fail "no startup error about $var in the logs"
  echo "ok: empty $var blocks the startup"
  docker compose -p smoke-empty down -v --remove-orphans
done
rm -f .env

# --- 4. Upgrade from the last release on an existing volume ---------------------------
step "Upgrade from the last release"
tag=$(git tag --list 'v[0-9]*' --sort=-v:refname | head -n1)
[ -n "$tag" ] || fail "no release tag found (fetch the tags)"
echo "last release: $tag"
mkdir -p "$WORK/old"
git show "$tag:docker-compose.yml" > "$WORK/old/docker-compose.yml"
write_env "$WORK/old/.env" "PALABRE_VERSION=${tag#v}"
(
  cd "$WORK/old"
  docker compose -p smoke-upgrade pull db backend
  docker compose -p smoke-upgrade up -d --wait --wait-timeout 180 db backend
)
wait_health 30 || fail "release $tag does not answer on /health"
# Data written by the old version: a row, and files as the old backend (uid 1000) left them
docker compose -p smoke-upgrade exec -T db psql -q -U palabre -d palabre \
  -c "create table smoke_marker(v text); insert into smoke_marker values ('kept');"
docker compose -p smoke-upgrade exec -T -u palabre backend sh -c \
  'mkdir -p /data/projects/project-1/repo /data/projects/project-1/worktrees/task-1 && echo kept > /data/projects/project-1/repo/file && echo kept > /data/projects/project-1/worktrees/task-1/file'
docker compose -p smoke-upgrade down   # keeps the volumes

write_env .env
export COMPOSE_PROJECT_NAME=smoke-upgrade
docker compose build backend
docker compose up -d --wait --wait-timeout 180 db backend
wait_health 30 || fail "current backend does not answer on the upgraded volume"
assert_secrets_resolved smoke-upgrade
assert_no_secret_in_env smoke-upgrade
[ "$(docker compose exec -T db psql -tA -U palabre -d palabre -c 'select v from smoke_marker')" = kept ] \
  || fail "database content lost in the upgrade"
docker compose exec -T backend test -f /data/.isolation-v1 || fail "volume migration marker missing"
[ "$(docker compose exec -T backend cat /data/projects/project-1/repo/file)" = kept ] || fail "repo file lost"
[ "$(docker compose exec -T backend stat -c '%U %a' /data/projects/project-1/repo)" = "palabre 700" ] \
  || fail "reference clone not private to palabre after the upgrade"
[ "$(docker compose exec -T backend stat -c %G /data/projects/project-1/worktrees/task-1)" = work ] \
  || fail "task clone not in group work after the upgrade"
echo "ok: upgrade from $tag"
echo; echo "Compose smoke test passed"
