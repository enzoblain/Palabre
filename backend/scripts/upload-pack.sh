#!/bin/sh
# Serves one task clone to the backend's fetch (#193), as the agent account that owns the clone: whatever the agent
# put in its .git (alternates, commondir, symlinks...), the OS only lets this process read what that account can.
# Installed root-owned, run through a sudo rule. Only the exact shape of a task clone path is accepted, so the
# rule is not a general git. --strict wants a git dir itself, hence $1/.git (a work tree is not one). The config is pinned on the command line: nothing in the clone runs code.
# The projects root is written root-owned at image build (PROJECTS_DIR), never taken from the caller's environment: a missing or odd root refuses everything.
set -eu
CONF="${PALABRE_PROJECTS_CONF:-/etc/palabre/projects-dir.conf}"
ROOT=$(cat "$CONF" 2>/dev/null) || { echo "no projects root configured" >&2; exit 2; }
case "$ROOT" in
  /*[!A-Za-z0-9/_-]*|*/|/|"") echo "bad projects root: $ROOT" >&2; exit 2 ;;
  /*) ;;
  *) echo "bad projects root: $ROOT" >&2; exit 2 ;;
esac
[ "$#" -eq 1 ] || { echo "usage: upload-pack <task clone path>" >&2; exit 2; }
# No newline, dot or other odd character: the pattern below then matches the whole argument
case "$1" in
  *[!A-Za-z0-9/_-]*) echo "not a task clone path: $1" >&2; exit 2 ;;
esac
printf '%s\n' "$1" | grep -Eq "^$ROOT/project-[0-9]+/worktrees/task-[0-9]+\$" \
  || { echo "not a task clone path: $1" >&2; exit 2; }
[ -d "$1" ] && [ ! -L "$1" ] || { echo "not a directory: $1" >&2; exit 2; }
exec /usr/bin/env GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null /usr/bin/git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c protocol.allow=never \
  -c credential.helper= -c core.askPass= -c "safe.directory=$1/.git" upload-pack --strict "$1/.git"
