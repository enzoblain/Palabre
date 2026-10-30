#!/bin/sh
# Serves one task clone to the backend's fetch (#193), as the agent account that owns the clone: whatever the agent
# put in its .git (alternates, commondir, symlinks...), the OS only lets this process read what that account can.
# Installed root-owned, run through a sudo rule. Only the exact shape of a task clone path is accepted, so the
# rule is not a general git. --strict wants a git dir itself, hence $1/.git (a work tree is not one). The config is pinned on the command line: nothing in the clone runs code.
set -eu
[ "$#" -eq 1 ] || { echo "usage: upload-pack <task clone path>" >&2; exit 2; }
# No newline, dot or other odd character: the pattern below then matches the whole argument
case "$1" in
  *[!A-Za-z0-9/_-]*) echo "not a task clone path: $1" >&2; exit 2 ;;
esac
printf '%s\n' "$1" | grep -Eq '^/data/projects/project-[0-9]+/worktrees/task-[0-9]+$' \
  || { echo "not a task clone path: $1" >&2; exit 2; }
[ -d "$1" ] && [ ! -L "$1" ] || { echo "not a directory: $1" >&2; exit 2; }
# sudo's env_reset drops GIT_PROTOCOL, so the fetch always talks protocol v0 (no v2 negotiation), also in the shared-account mode.
exec /usr/bin/env GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null /usr/bin/git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c protocol.allow=never \
  -c credential.helper= -c core.askPass= -c "safe.directory=$1/.git" upload-pack --strict "$1/.git"
