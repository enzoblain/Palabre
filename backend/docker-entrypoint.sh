#!/bin/sh
# Sets up /data for the two users (palabre: the backend, agent: the agents' runs), then
# drops root and starts the backend. Idempotent: safe on a fresh volume and on a volume
# from an older version, where everything belongs to palabre (uid 1000).
set -eu

if [ "$(id -u)" != "0" ]; then
  exec "$@"
fi

DATA=/data
mkdir -p "$DATA/projects" "$DATA/runtime" "$DATA/toolchains" "$DATA/claude"

# Common group "work", setgid so new files keep it. Agents may only cross /data and
# /data/projects (no listing of /data, no renaming of a project); they write in the clones
# of tasks and desks, in Claude's sessions and in the Go cache. Only the quick,
# non-recursive fixes run at every start.
chown palabre:work "$DATA" "$DATA/projects" "$DATA/toolchains" "$DATA/claude"
chmod 2710 "$DATA"
chmod 2751 "$DATA/projects" "$DATA/toolchains"
chmod 2775 "$DATA/claude"
mkdir -p "$DATA/toolchains/gopath"
chown palabre:work "$DATA/toolchains/gopath"
chmod 2775 "$DATA/toolchains/gopath"
# The backend alone: runtime holds the MCP tokens of the runs
chown palabre:palabre "$DATA/runtime"
chmod 700 "$DATA/runtime"

# Migration of a volume made before the isolation: one pass, then a marker
if [ ! -e "$DATA/.isolation-v1" ]; then
  for dir in projects toolchains claude; do
    chgrp -R work "$DATA/$dir"
    chmod -R g+rX,g-w "$DATA/$dir"
    find "$DATA/$dir" -type d -exec chmod g+s {} +
  done
  # What the agents write in
  for dir in claude toolchains/gopath; do
    chmod -R g+rwX "$DATA/$dir"
  done
  for dir in "$DATA"/projects/project-*/desks "$DATA"/projects/project-*/worktrees; do
    [ -d "$dir" ] && chmod -R g+rwX "$dir"
  done
  touch "$DATA/.isolation-v1"
fi

# The project's reference clone holds the GitHub remote config: the backend only
for repo in "$DATA"/projects/project-*/repo; do
  [ -d "$repo" ] || continue
  chown -R palabre:palabre "$repo"
  chmod -R go-rwx "$repo"
done

umask 002
exec setpriv --reuid=palabre --regid=palabre --init-groups "$@"
