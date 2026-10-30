#!/bin/sh
# Sets up /data for the two users (palabre: the backend, agent: the agents' runs), then
# drops root and starts the backend. Idempotent: safe on a fresh volume and on a volume
# from an older version, where everything belongs to palabre (uid 1000).
set -eu

if [ "$(id -u)" != "0" ]; then
  exec tini -s -- "$@"
fi

DATA=/data

# The next steps run as root on a volume the agents could once write in: never follow a
# symlink they may have planted (chmod/chown follow one given on the command line)
real_dir() { [ -d "$1" ] && [ ! -L "$1" ]; }

mkdir -p "$DATA/projects" "$DATA/runtime" "$DATA/run" "$DATA/toolchains" "$DATA/claude"
for dir in projects runtime run toolchains claude; do
  real_dir "$DATA/$dir" || { echo "$DATA/$dir is not a plain directory" >&2; exit 1; }
done

# Claude's sessions: the backend's store, one directory per employee. Agents get a
# throwaway config dir per run (in $DATA/run) and never see this one.
chown palabre:palabre "$DATA/claude"
chmod 700 "$DATA/claude"

# Common group "work", setgid so new files keep it. Agents may only cross /data and
# /data/projects (no listing of /data, no renaming of a project) and read the toolchains.
# They write in nothing shared: the clone of a run and its Go cache are handed to the run's
# account by the backend (palabre-claim-clone, #160).
chown palabre:work "$DATA" "$DATA/projects" "$DATA/toolchains"
chmod 2710 "$DATA"
chmod 2751 "$DATA/projects" "$DATA/toolchains"
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
  for dir in projects toolchains; do
    real_dir "$DATA/$dir" || continue
    chgrp -R work "$DATA/$dir"
    chmod -R g+rX,g-w "$DATA/$dir"
    find "$DATA/$dir" -type d -exec chmod g+s {} +
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
for project in "$DATA"/projects/project-*; do
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
    # The clones themselves: back to the backend at every start (a run's account may have left
    # files in them); the next run claims its clone. -h: never follow a planted symlink.
    find -P "$project/$parent" -mindepth 1 -maxdepth 1 -type d -exec chown -hR palabre:palabre {} +
    find -P "$project/$parent" -mindepth 1 -maxdepth 1 -type d -exec chmod -R u+rwX,g+rwX,go-s,o-rwx {} +
  done
done

# Per-employee Go caches: same as the clones, back to the backend at every start (a run's
# account may have left files in them); the next run of the employee claims its cache.
if real_dir "$DATA/toolchains/gopath"; then
  find -P "$DATA/toolchains/gopath" -mindepth 1 -maxdepth 1 -type d -name 'employee-*' -exec chown -hR palabre:palabre {} +
  find -P "$DATA/toolchains/gopath" -mindepth 1 -maxdepth 1 -type d -name 'employee-*' -exec chmod -R u+rwX,g+rwX,go-s,o-rwx {} +
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
