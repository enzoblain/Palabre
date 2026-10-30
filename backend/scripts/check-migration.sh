#!/bin/sh
# Checks the entrypoint's migration of a /data volume made before the agent user (#101).
# Run on a machine with Docker, from the host (nothing is touched but a temporary volume):
#   backend/scripts/check-migration.sh <image>
# Exits non-zero if the migration leaves something wrong.
set -u

image=${1:?usage: check-migration.sh <image>}
volume=palabre-check-migration-$$
fail=0
nok=0
nfail=0
trap 'docker volume rm -f "$volume" >/dev/null 2>&1' EXIT
root() { docker run --rm --user root --entrypoint sh -v "$volume:/data" "$image" -c "$1"; }
check() { # description, then a root shell command that must succeed on the volume
  if root "$2" >/dev/null 2>&1; then echo "ok   $1"; nok=$((nok + 1)); else echo "FAIL $1"; fail=1; nfail=$((nfail + 1)); fi
}

# A volume as the previous versions left it: everything belongs to palabre (uid 1000), 0755
root '
  mkdir -p /data/projects/project-1/repo/.git /data/projects/project-1/worktrees/task-5/.git \
           /data/projects/project-1/desks/employee-2 /data/toolchains/bin /data/toolchains/gopath/pkg \
           /data/claude/projects /data/runtime
  echo "[remote]" > /data/projects/project-1/repo/.git/config
  echo x > /data/projects/project-1/worktrees/task-5/file
  echo x > /data/toolchains/bin/node
  echo x > /data/claude/session.json
  mkdir -p /data/claude/employee-1/projects/p && echo x > /data/claude/employee-1/projects/p/planted.jsonl
  chown -R 1000:1000 /data
  chmod -R 755 /data
  rm -f /data/.isolation-v1 /data/.isolation-v2
' || { echo "FAIL cannot prepare the old volume"; exit 1; }

# The image's own entrypoint, as docker compose runs it, then a command as the backend
docker run --rm -v "$volume:/data" "$image" sh -c '[ "$(id -un)" = palabre ] && test -f /data/.isolation-v1' >/dev/null 2>&1 \
  && { echo "ok   the entrypoint runs on the old volume and drops to palabre, marker written"; nok=$((nok + 1)); } \
  || { echo "FAIL the entrypoint fails on the old volume"; fail=1; nfail=$((nfail + 1)); }

check "the marker .isolation-v1 exists" 'test -f /data/.isolation-v1'
check "the volume belongs to group work, closed to others" '[ "$(stat -c %G:%a /data)" = "work:2710" ]'
# setgid (2700) is fine: the migration's find sets it on every directory, the mode stays closed to others
check "the reference clone is private to palabre" \
  'case "$(stat -c %U:%a /data/projects/project-1/repo)" in palabre:700|palabre:2700) true ;; *) false ;; esac'
check "the task clone is group-writable (agents commit there)" \
  '[ "$(stat -c %G /data/projects/project-1/worktrees/task-5/file)" = work ] && stat -c %A /data/projects/project-1/worktrees/task-5/file | grep -q "^-rw.rw"'
check "the task clone is closed to others (o-rwx)" \
  '[ -z "$(find /data/projects/project-1/worktrees -perm /007)" ]'
check "runtime is the backend's only" '[ "$(stat -c %U:%a /data/runtime)" = "palabre:700" ]'
check "legacy shared claude sessions are purged" '! test -e /data/claude/session.json && ! test -e /data/claude/projects && ! test -e /data/claude/employee-1'
check "the claude store is private to palabre" '[ "$(stat -c %U:%a /data/claude)" = "palabre:700" ]'
check "the agent cannot read the claude store" '! setpriv --reuid=agent --regid=work --init-groups ls /data/claude'
check "the agent can write in its task clone" \
  'setpriv --reuid=agent --regid=work --init-groups touch /data/projects/project-1/worktrees/task-5/new'
check "the agent cannot read the reference" \
  '! setpriv --reuid=agent --regid=work --init-groups ls /data/projects/project-1/repo'
check "a pool account (agent1) cannot read the claude store" \
  '! setpriv --reuid=agent1 --regid=work --init-groups ls /data/claude'
check "a pool account (agent1) cannot read the reference" \
  '! setpriv --reuid=agent1 --regid=work --init-groups ls /data/projects/project-1/repo'
check "a pool account (agent1) can write in its task clone" \
  'setpriv --reuid=agent1 --regid=work --init-groups touch /data/projects/project-1/worktrees/task-5/new1'

# A second start must change nothing (the marker makes the one-time part a no-op)
docker run --rm -v "$volume:/data" "$image" true >/dev/null 2>&1 \
  && { echo "ok   a second start succeeds"; nok=$((nok + 1)); } \
  || { echo "FAIL a second start fails"; fail=1; nfail=$((nfail + 1)); }
echo "check-migration: $nok ok, $nfail FAIL"
exit $fail
