#!/bin/sh
# Sets up /data for the two users (palabre: the backend, agent: the agents' runs), then
# drops root and starts the backend. Idempotent: safe on a fresh volume and on a volume
# from an older version, where everything belongs to palabre (uid 1000).
set -eu

if [ "$(id -u)" != "0" ]; then
  exec tini -s -- "$@"
fi

DATA=/data

# The projects root is the one the root scripts and sudo rules were bound to at image build (PROJECTS_DIR).
# Stricter than palabre-claim-clone: it is chowned and chmodded as root below, so it must be a subdirectory
# of /data that is not one of the directories managed here. The runtime PROJECTS_DIR, when set, must match
# it: otherwise the backend would write clones where neither the sudo rules nor this script apply, so refuse
# to start (an empty one is refused too).
PROJECTS=$(cat /etc/palabre/projects-root.conf 2>/dev/null) || { echo "no projects root configured" >&2; exit 1; }
case "$PROJECTS" in
  /*[!A-Za-z0-9/_-]*|*/|/|""|*//*) echo "bad projects root: $PROJECTS" >&2; exit 1 ;;
  /data/run|/data/run/*|/data/runtime|/data/runtime/*|/data/claude|/data/claude/*|/data/toolchains|/data/toolchains/*)
    echo "projects root $PROJECTS overlaps a directory managed by this entrypoint" >&2; exit 1 ;;
  /data/?*) ;;
  *) echo "bad projects root: $PROJECTS" >&2; exit 1 ;;
esac
if [ "${PROJECTS_DIR+set}" = set ] && [ -z "$PROJECTS_DIR" ]; then
  echo "PROJECTS_DIR is set but empty: unset it or give it the projects root of this image ($PROJECTS)" >&2
  exit 1
fi
if [ "${PROJECTS_DIR-$PROJECTS}" != "$PROJECTS" ]; then
  echo "PROJECTS_DIR=$PROJECTS_DIR differs from the projects root of this image ($PROJECTS): rebuild with that PROJECTS_DIR" >&2
  exit 1
fi

# Note: _entrypoint_guard in the tests runs everything above the marker below.
# The next steps run as root on a volume the agents could once write in: never follow a
# symlink they may have planted (chmod/chown follow one given on the command line)
real_dir() { [ -d "$1" ] && [ ! -L "$1" ]; }

# Gives a clone (or Go cache) back to the backend, private to it, as claim-clone.sh does after a run.
# Skipped when nothing in it is foreign or open to group/others (a symlink is always 777: ignored).
# Keep in sync with worktrees._share_with_group, which applies the same rights to fresh clones.
take_back() {
  real_dir "$1" || return 0
  [ -n "$(find -P "$1" \( ! -user palabre -o ! -group palabre -o \( ! -type l -perm /go+rwx \) \) -print -quit)" ] || return 0
  chown -hR palabre:palabre "$1"
  chmod -R u+rwX,go-rwx,ug-s "$1"
}

# Shared account (AGENT_POOL_SIZE<=0): nothing claims a clone per run, so the one agent account reaches
# them through the group "work" instead. With a pool, clones stay the backend's until a run claims them.
shared_account=0
if [ "${AGENT_POOL_SIZE:-0}" -le 0 ] 2>/dev/null && [ -n "${AGENT_USER:-}" ] && [ "${AGENT_USER}" != palabre ]; then
  shared_account=1
fi

# Legacy counterpart of take_back: group work, group-writable, setgid dirs, so the shared agent can write in
# the clone and serve it to palabre-upload-pack. Skipped when already so (a symlink is always 777: ignored).
# Keep in sync with worktrees._share_with_group, which applies the same rights to fresh clones.
share_back() {
  real_dir "$1" || return 0
  [ -n "$(find -P "$1" \( ! -group work -o \( -type d ! -perm -g+s \) -o \( ! -type l ! -perm -g+rw \) \) -print -quit)" ] || return 0
  chgrp -hR work "$1"
  chmod -R g+rwX "$1"
  find -P "$1" -type d -exec chmod g+s {} +
}

# Per-clone hand-back at start: private to the backend with a pool, shared with the agent group (work) without
claim_back() {
  if [ "$shared_account" = 1 ]; then share_back "$1"; else take_back "$1"; fi
}

mkdir -p "$PROJECTS" "$DATA/runtime" "$DATA/run" "$DATA/toolchains" "$DATA/claude"
for dir in "$PROJECTS" "$DATA/runtime" "$DATA/run" "$DATA/toolchains" "$DATA/claude"; do
  real_dir "$dir" || { echo "$dir is not a plain directory" >&2; exit 1; }
done

# Claude's sessions: the backend's store, one directory per employee. Agents get a
# throwaway config dir per run (in $DATA/run) and never see this one.
chown palabre:palabre "$DATA/claude"
chmod 700 "$DATA/claude"

# Common group "work", setgid so new files keep it. Agents may only cross /data and
# the projects root (no listing of /data, no renaming of a project) and read the toolchains.
# They write in nothing shared: the clone of a run and its Go cache are handed to the run's
# account by the backend (palabre-claim-clone, #160).
chown palabre:work "$DATA" "$PROJECTS" "$DATA/toolchains"
chmod 2710 "$DATA"
chmod 2751 "$PROJECTS" "$DATA/toolchains"
# Go caches: one directory per employee inside, claimed by the backend for each run
real_dir "$DATA/toolchains/gopath" || rm -f "$DATA/toolchains/gopath"
mkdir -p "$DATA/toolchains/gopath"
chown palabre:work "$DATA/toolchains/gopath"
chmod 2751 "$DATA/toolchains/gopath"
# The backend alone: runtime holds the MCP tokens of the runs
chown palabre:palabre "$DATA/runtime"
chmod 700 "$DATA/runtime"
# MCP configs the agent reads: crossed, never listed
chown palabre:work "$DATA/run"
chmod 2711 "$DATA/run"

# Migration of a volume made before the isolation: one pass, then a marker
if [ ! -e "$DATA/.isolation-v1" ]; then
  for dir in "$PROJECTS" "$DATA/toolchains"; do
    real_dir "$dir" || continue
    chgrp -R work "$dir"
    chmod -R g+rX,g-w "$dir"
    find "$dir" -type d -exec chmod g+s {} +
  done
  touch "$DATA/.isolation-v1"
fi

# The Go cache was one directory every run wrote in and executed from: drop it (go downloads
# again). Clones were group-writable by every run: they are the backend's until a run claims them.
if [ ! -e "$DATA/.isolation-v3" ]; then
  if real_dir "$DATA/toolchains/gopath"; then
    find -P "$DATA/toolchains/gopath" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  fi
  touch "$DATA/.isolation-v3"
fi

# Sessions written in the shared config dir cannot be trusted or told apart by employee: purge them
# (agents start a new session on their next run) and make everything left the backend's.
if [ ! -e "$DATA/.isolation-v2" ]; then
  if real_dir "$DATA/claude"; then
    # Everything: the directory was group-writable, so even an employee-* directory could be planted
    find -P "$DATA/claude" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    chown -R palabre:palabre "$DATA/claude"
    chmod -R go-rwx "$DATA/claude"
  fi
  touch "$DATA/.isolation-v2"
fi

# Per project, at every start (these scale with the size of the repositories). Agents only
# write inside their own clone: the directories holding the clones stay closed to them.
for project in "$PROJECTS"/project-*; do
  real_dir "$project" || continue
  chmod 2755 "$project"
  # The reference clone holds the GitHub remote config: the backend only
  if real_dir "$project/repo"; then
    chown -R palabre:palabre "$project/repo"
    chmod -R go-rwx "$project/repo"
  fi
  for parent in desks worktrees; do
    real_dir "$project/$parent" || continue
    chown palabre:work "$project/$parent"
    chmod 2755 "$project/$parent"
    # The clones themselves: back to the backend (a run's account may have left files in them); the next
    # run claims its clone. Same rights as claim-clone.sh gives back: private to the backend. Only a clone with
    # something not yet palabre:palabre is walked, so the cost does not grow with the number of finished tasks.
    # -h: never follow a planted symlink.
    for clone in "$project/$parent"/*; do
      claim_back "$clone"
    done
  done
done

# Per-employee Go caches: same as the clones, back to the backend at every start (a run's
# account may have left files in them); the next run of the employee claims its cache.
if real_dir "$DATA/toolchains/gopath"; then
  for cache in "$DATA"/toolchains/gopath/employee-*; do
    claim_back "$cache"
  done
fi

# Secrets: Docker mounts them readable by everyone in /run/secrets. Close that directory
# and hand the backend its own private copy, so no agent (or child process) can read them.
if [ -d /run/secrets ]; then
  install -d -o palabre -g palabre -m 500 /run/palabre-secrets
  for f in /run/secrets/*; do
    [ -f "$f" ] || continue
    install -o palabre -g palabre -m 400 "$f" "/run/palabre-secrets/$(basename "$f")"
  done
  chmod 700 /run/secrets
fi

umask 002
# tini after the drop: PID 1 stays palabre and reaps the orphans of killed agent runs
exec setpriv --reuid=palabre --regid=palabre --init-groups tini -s -- "$@"
