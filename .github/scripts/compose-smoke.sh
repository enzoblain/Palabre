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

# The highest published version, if any: release tags live on main, so describe from dev would
# find an old one. The image tags have no "v".
OLD=""
git fetch --tags --quiet 2>/dev/null || true
tag=$(git tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname | sed -n 1p) || true
if [ -n "$tag" ]; then OLD="${tag#v}"; fi
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
  code=$(http_code "http://127.0.0.1:$PORT/api/catalog/modes")
  [ "$code" = 401 ] || fail "$1: /api without token answered $code (expected 401)"
  code=$(http_code -H "Authorization: Bearer wrong-$ADMIN_TOKEN" "http://127.0.0.1:$PORT/api/catalog/modes")
  [ "$code" = 401 ] || fail "$1: /api with a wrong token answered $code (expected 401)"
  code=$(http_code -H "Authorization: Bearer $ADMIN_TOKEN" "http://127.0.0.1:$PORT/api/catalog/modes")
  [ "$code" = 200 ] || fail "$1: /api with the right token answered $code (expected 200)"
}

# The web app's security headers, on the page and on a hashed asset (which has its own location)
check_web_headers() { # check_web_headers <label>
  local base="http://127.0.0.1:12810" asset url headers h
  asset=$(curl -fs "$base/" | grep -oE '/assets/[^"]+\.js' | sed -n 1p) || true
  [ -n "$asset" ] || fail "$1: no /assets/*.js referenced by the web app's index.html"
  for url in "$base/" "$base$asset"; do
    headers=$(curl -fsI "$url" | tr -d '\r' | tr 'A-Z' 'a-z') || fail "$1: $url did not answer"
    for h in content-security-policy: "frame-ancestors 'none'" x-content-type-options:\ nosniff; do
      case "$headers" in *"$h"*) ;; *) fail "$1: $url lacks '$h'";; esac
    done
  done
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
  # Unreadable (non-dumpable process after the privilege drop) is no leak: the shell error ends up in $out
  out=$(dc exec -T backend sh -c 'tr "\0" "\n" < /proc/1/environ' 2>&1 || true)
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
  # The agent user comes through sudo's env_reset: its env must be clean too
  out=$(dc exec -T -u agent backend env)
  check_no_secret_in "$1: env of the agent user" "$out"
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
  # Right after a release tag, the images may not be built yet: retry for a few minutes
  attempts=${SMOKE_PULL_ATTEMPTS:-8}
  for ((n = 1; n <= attempts; n++)); do
    if out=$(dc pull db backend 2>&1); then break; fi
    if [ "$n" -eq "$attempts" ]; then
      echo "$out"
      fail "image palabre:$OLD not published on ghcr yet (or palabre-web): the pull failed $attempts times. Last output: $(printf '%s' "$out" | tail -n 3)"
    fi
    note "pull of $OLD failed (attempt $n/$attempts), retrying in ${SMOKE_PULL_DELAY:-30}s"
    sleep "${SMOKE_PULL_DELAY:-30}"
  done
  if ! docker run --rm --entrypoint grep "ghcr.io/enzoblain/palabre:$OLD" -q palabre-secrets /usr/local/bin/docker-entrypoint.sh; then
    [ -z "${GITHUB_ACTIONS:-}" ] || fail "$OLD predates Docker secrets: the upgrade and updater steps would be skipped"
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
  [ -z "${GITHUB_ACTIONS:-}" ] || fail "No published version to upgrade from: the upgrade and updater steps would be skipped"
  note "No published version to upgrade from: upgrade and updater steps skipped"
fi

# --- Fresh start of the version under test ------------------------------------------------
step "Fresh start of the version under test"
write_env "$NEW"
dc build backend
dc build web
dc up -d --wait --wait-timeout 120 db backend web || fail "the new version did not become healthy on a fresh volume"
check_web_headers "fresh start"
check_api "fresh start"
check_secrets "fresh start"

# The pool of agent accounts on a real container: no run is going on in the smoke stack, so the
# script may swap claude for its stub. The exit code is the verdict.
step "Agent pool isolation (agent1..N)"
# The output is captured and replayed: a workflow command only counts at the start of a line,
# and GitHub keeps 10 annotations per step, so on failure the ::error lines are re-emitted
# bare, most informative first (kill blocks, other FAILs, raw dumps), and the dumps go in groups.
iso_out=$(mktemp)
iso_rc=0
dc exec -T -u root -e CHECK_POOL_ONLY=1 backend /srv/scripts/check-isolation.sh >"$iso_out" 2>&1 || iso_rc=$?
tr -d '\r' <"$iso_out" | sed 's/^[[:space:]]*\(::\)/\1/' >"$iso_out.clean"
if [ "$iso_rc" -eq 0 ]; then
  cat "$iso_out.clean"
else
  # The dumps sit between stop-commands markers: the sorted block below is the only place
  # where the ::error lines are live.
  token=$(date +%s%N)
  echo "::stop-commands::$token"
  echo "::group::check-isolation.sh, full output (exit $iso_rc)"
  cat "$iso_out.clean"
  echo "::endgroup::"
  echo "::group::check-isolation.sh, last 40 lines"
  tail -n 40 "$iso_out.clean"
  echo "::endgroup::"
  echo "::$token::"
  grep '^FAIL ' "$iso_out.clean" || true
  # Kill blocks first, then the other FAILs, then the sudo -ll dumps; 8 at most, plus the final fail.
  { grep -E '^::error::no (live )?agent process' "$iso_out.clean" || true
    grep '^::error::' "$iso_out.clean" | grep -vE '^::error::(no (live )?agent process|sudo -ll)' || true
    grep '^::error::sudo -ll' "$iso_out.clean" || true; } | head -n 8
  nfail=$(grep -c '^FAIL ' "$iso_out.clean" || true)
fi
rm -f "$iso_out" "$iso_out.clean"
[ "$iso_rc" -eq 0 ] || fail "the agent isolation check failed (exit $iso_rc, $nfail FAIL line(s)); details in the annotations above"

# The entrypoint's migration of an old volume, on the image just built. The "ok" lines and the
# final count stay in the log: a check that did not run must not look like one that passed.
step "Migration of a volume made before the agent user"
# 1 entrypoint check + 13 checks + 1 second start; keep in sync with check-migration.sh
MIG_EXPECTED_OK=15
mig_rc=0
mig_out=$(backend/scripts/check-migration.sh "ghcr.io/enzoblain/palabre:$NEW" 2>&1) || mig_rc=$?
printf '%s\n' "$mig_out"
[ "$mig_rc" -eq 0 ] || fail "check-migration.sh failed (exit $mig_rc): $(printf '%s' "$mig_out" | { grep '^FAIL ' || true; } | head -n 3 | tr '\n' ';')"
# Pin the summary line: with the number of checks fixed, a check that silently vanished fails too
printf '%s\n' "$mig_out" | grep -qxE "check-migration: $MIG_EXPECTED_OK ok, 0 FAIL" \
  || fail "check-migration.sh summary is not 'check-migration: $MIG_EXPECTED_OK ok, 0 FAIL' (it did not run, or a check was added or removed: update MIG_EXPECTED_OK)"

echo "Compose smoke test passed"
