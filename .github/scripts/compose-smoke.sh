#!/usr/bin/env bash
# Smoke test of docker-compose.yml: secrets as files and nowhere else, agent isolation, the
# updater, and an upgrade from the last published version on an existing volume.
# Needs docker; run from anywhere. It writes its own .env in the repository (removed on exit),
# so it refuses to run over a real .env or an override file.
set -Eeuo pipefail

cd "$(dirname "$0")/../.."

fail() { echo "::error title=Compose smoke test::$*"; exit 1; }
note() { echo "::notice title=Compose smoke test::$*"; }
step() { echo "--- $*"; }
# Any other failing command (pull, build, exec...) gets an annotation too, not a bare exit code.
# The trap does not fire for commands tested by if/||/&&, which report their own failure.
trap 'echo "::error title=Compose smoke test::line $LINENO: \`$BASH_COMMAND\` failed"' ERR

for f in .env docker-compose.override.yml docker-compose.override.yaml compose.override.yml compose.override.yaml; do
  [ ! -e "$f" ] || fail "$f exists: this script would clobber it. Move it away first."
done

ADMIN_TOKEN="smoke-admin-$(openssl rand -hex 12)"
GITHUB_TOKEN="smoke-github-$(openssl rand -hex 12)"
CLAUDE_CODE_OAUTH_TOKENS="smoke-claude-$(openssl rand -hex 12)"
POSTGRES_PASSWORD="smoke-pg-$(openssl rand -hex 12)"
SECRETS=("$ADMIN_TOKEN" "$GITHUB_TOKEN" "$CLAUDE_CODE_OAUTH_TOKENS" "$POSTGRES_PASSWORD")
SECRET_FILES=(admin_token github_token claude_code_oauth_tokens postgres_password)
PORT=12710

# The last published version, if any: the image tags have no "v"
OLD=""
if tag=$(git describe --tags --abbrev=0 --match 'v*' 2>/dev/null); then OLD="${tag#v}"; fi
NEW="smoke-local"

write_env() {
  cat > .env <<ENV
ADMIN_TOKEN=$ADMIN_TOKEN
GITHUB_TOKEN=$GITHUB_TOKEN
CLAUDE_CODE_OAUTH_TOKENS=$CLAUDE_CODE_OAUTH_TOKENS
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
COMPOSE_PROJECT_NAME=palabre-smoke
PALABRE_VERSION=$1
PALABRE_PORT=$PORT
PALABRE_WEB_PORT=12810
PALABRE_UPDATE_INTERVAL=5
ENV
}

dc() { docker compose "$@"; }

cleanup() {
  code=$?
  if [ "$code" -ne 0 ]; then
    echo "::group::docker compose ps / logs"
    dc --profile autoupdate ps -a || true
    dc --profile autoupdate logs --no-color --tail 80 || true
    echo "::endgroup::"
  fi
  dc --profile autoupdate down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f .env
  exit "$code"
}
trap cleanup EXIT

backend_id() { dc ps -q backend; }

wait_healthy() { # wait_healthy <seconds>
  local id status
  for ((i = 0; i < $1 / 2; i++)); do
    id=$(backend_id)
    if [ -n "$id" ]; then
      status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id")
      [ "$status" != healthy ] || return 0
    fi
    sleep 2
  done
  return 1
}

http_code() { # http_code [curl args...]
  curl -s -o /dev/null -w '%{http_code}' "$@" || true
}

check_api() {
  local code
  code=$(http_code "http://127.0.0.1:$PORT/health")
  [ "$code" = 200 ] || fail "$1: /health answered $code"
  code=$(http_code "http://127.0.0.1:$PORT/api/modes")
  [ "$code" = 401 ] || fail "$1: /api without token answered $code (expected 401)"
  code=$(http_code -H "Authorization: Bearer wrong-$ADMIN_TOKEN" "http://127.0.0.1:$PORT/api/modes")
  [ "$code" = 401 ] || fail "$1: /api with a wrong token answered $code (expected 401)"
  code=$(http_code -H "Authorization: Bearer $ADMIN_TOKEN" "http://127.0.0.1:$PORT/api/modes")
  [ "$code" = 200 ] || fail "$1: /api with the right token answered $code (expected 200)"
}

check_no_secret_in() { # check_no_secret_in <label> <text>
  local s
  for s in "${SECRETS[@]}"; do
    case "$2" in *"$s"*) fail "$1 contains a secret ($(printf '%s' "$s" | cut -d- -f1-2)-...)";; esac
  done
}

check_secrets() { # check_secrets <label>
  local id out f
  id=$(backend_id)
  [ -n "$id" ] || fail "$1: no backend container"
  # As root, the strongest reader: the secrets must not be in the environment at all
  out=$(dc exec -T backend env)
  check_no_secret_in "$1: env of the backend" "$out"
  out=$(dc exec -T backend sh -c 'tr "\0" "\n" < /proc/1/environ')
  check_no_secret_in "$1: /proc/1/environ" "$out"
  out=$(docker inspect "$id")
  check_no_secret_in "$1: docker inspect backend" "$out"
  out=$(docker inspect "$(dc ps -q db)")
  check_no_secret_in "$1: docker inspect db" "$out"

  # The backend's private copy is there and holds the right values
  out=$(dc exec -T backend cat /run/palabre-secrets/admin_token)
  [ "$out" = "$ADMIN_TOKEN" ] || fail "$1: /run/palabre-secrets/admin_token does not hold the secret"

  # The files must exist for the read checks below to mean something
  for f in "${SECRET_FILES[@]}"; do
    dc exec -T backend test -f "/run/secrets/$f" || fail "$1: /run/secrets/$f is not mounted"
    dc exec -T backend test -f "/run/palabre-secrets/$f" || fail "$1: /run/palabre-secrets/$f is missing"
  done
  # The agent user must exist, otherwise the checks below prove nothing
  dc exec -T backend id agent >/dev/null 2>&1 || fail "$1: the user 'agent' does not exist in the image"
  for f in "${SECRET_FILES[@]}"; do
    for dir in /run/secrets /run/palabre-secrets; do
      if dc exec -T -u agent backend sh -c "[ -r $dir/$f ] || cat $dir/$f" >/dev/null 2>&1; then
        fail "$1: the agent user can read $dir/$f"
      fi
    done
  done
  for dir in /run/secrets /run/palabre-secrets; do
    if dc exec -T -u agent backend ls "$dir" >/dev/null 2>&1; then
      fail "$1: the agent user can list $dir"
    fi
  done
  # The backend still drops to palabre (not root)
  out=$(dc exec -T backend sh -c 'ps -o user= -p 1')
  [ "$out" = palabre ] || fail "$1: the server runs as '$out', not palabre"
}

# --- Upgrade from the last published version, on a volume it has used ---------------------
if [ -n "$OLD" ]; then
  step "Start the published $OLD"
  write_env "$OLD"
  # web is not started here: the updater pulls it, so it has to exist at this tag too
  dc pull db backend web || fail "could not pull the published $OLD (is the ghcr package public, was the release image pushed?)"
  if ! docker run --rm --entrypoint grep "ghcr.io/enzoblain/palabre:$OLD" -q palabre-secrets /usr/local/bin/docker-entrypoint.sh; then
    note "$OLD predates Docker secrets: the upgrade and updater steps are skipped"
    OLD=""
  fi
fi

if [ -n "$OLD" ]; then
  dc up -d --wait --wait-timeout 120 db backend || fail "published $OLD did not become healthy"
  check_api "published $OLD"
  # State the new version must find intact on the volume
  dc exec -T backend sh -c 'echo kept > /data/smoke-marker && mkdir -p /data/projects/project-1/repo && chown -R palabre:palabre /data/projects/project-1'

  step "Build the version under test over $OLD's tag"
  dc build backend
  dc up -d --wait --wait-timeout 120 backend || fail "the new version did not start on $OLD's volume"
  [ "$(dc exec -T backend cat /data/smoke-marker)" = kept ] || fail "the volume lost its data on upgrade"
  check_api "upgrade from $OLD"
  check_secrets "upgrade from $OLD"
  dc exec -T backend test -e /data/.isolation-v1 || fail "the entrypoint did not migrate the volume"

  step "Updater: the registry's image replaces the local one"
  before=$(backend_id)
  dc --profile autoupdate up -d updater
  for ((i = 0; i < 90; i++)); do
    [ "$(backend_id)" != "$before" ] && break
    sleep 2
  done
  if [ "$(backend_id)" = "$before" ]; then
    dc logs --no-color updater || true
    fail "the updater did not recreate the backend"
  fi
  wait_healthy 120 || fail "the backend did not become healthy after the updater recreated it"
  check_api "after the updater"
  check_secrets "after the updater"
  # The published image now runs on a volume the new version already migrated: a downgrade,
  # fine because the entrypoint migration is idempotent
  dc --profile autoupdate down -v --remove-orphans
else
  note "No published version to upgrade from: upgrade and updater steps skipped"
fi

# --- Fresh start of the version under test ------------------------------------------------
step "Fresh start of the version under test"
write_env "$NEW"
dc build backend
dc up -d --wait --wait-timeout 120 db backend || fail "the new version did not become healthy on a fresh volume"
check_api "fresh start"
check_secrets "fresh start"

echo "Compose smoke test passed"
