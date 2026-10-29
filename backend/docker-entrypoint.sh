#!/bin/sh
# Sets up /data for the two users (palabre: the backend, agent: the agents' runs), then
# drops root and starts the backend. Idempotent: safe on a fresh volume and on a volume
# from an older version, where everything belongs to palabre (uid 1000).
set -eu

if [ "$(id -u)" != "0" ]; then
  exec "$@"
fi

DATA=/data

# The next steps run as root on a volume the agents could once write in: never follow a
# symlink they may have planted (chmod/chown follow one given on the command line)
real_dir() { [ -d "$1" ] && [ ! -L "$1" ]; }

mkdir -p "$DATA/projects" "$DATA/runtime" "$DATA/toolchains" "$DATA/claude"
for dir in projects runtime toolchains claude; do
  real_dir "$DATA/$dir" || { echo "$DATA/$dir is not a plain directory" >&2; exit 1; }
done

# Common group "work", setgid so new files keep it. Agents may only cross /data and
# /data/projects (no listing of /data, no renaming of a project); they write in the clones
# of tasks and desks, in Claude's sessions and in the Go cache.
chown palabre:work "$DATA" "$DATA/projects" "$DATA/toolchains" "$DATA/claude"
chmod 2710 "$DATA"
chmod 2751 "$DATA/projects" "$DATA/toolchains"
chmod 2775 "$DATA/claude"
real_dir "$DATA/toolchains/gopath" || rm -f "$DATA/toolchains/gopath"
mkdir -p "$DATA/toolchains/gopath"
chown palabre:work "$DATA/toolchains/gopath"
chmod 2775 "$DATA/toolchains/gopath"
# The backend alone: runtime holds the MCP tokens of the runs
chown palabre:palabre "$DATA/runtime"
chmod 700 "$DATA/runtime"

# Migration of a volume made before the isolation: one pass, then a marker
if [ ! -e "$DATA/.isolation-v1" ]; then
  for dir in projects toolchains claude; do
    real_dir "$DATA/$dir" || continue
    chgrp -R work "$DATA/$dir"
    chmod -R g+rX,g-w "$DATA/$dir"
    find "$DATA/$dir" -type d -exec chmod g+s {} +
  done
  # What the agents write in
  for dir in "$DATA/claude" "$DATA/toolchains/gopath"; do
    real_dir "$dir" && chmod -R g+rwX "$dir"
  done
  touch "$DATA/.isolation-v1"
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
    # The clones themselves: group-writable, files included (migration from older volumes)
    find -P "$project/$parent" -mindepth 1 -maxdepth 1 -type d ! -perm -g=w -exec chmod -R g+rwX {} +
  done
done

umask 002
exec setpriv --reuid=palabre --regid=palabre --init-groups "$@"
