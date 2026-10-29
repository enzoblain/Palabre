#!/bin/sh
# Deletes one desk or task clone as the agent user (#130): files the agent created outside the
# shared group cannot be removed by the backend. Installed root-owned, run through a sudo rule.
# Only the exact shape of a clone path is accepted, so the rule is not a general rm.
set -eu
[ "$#" -eq 1 ] || { echo "usage: rm-clone <clone path>" >&2; exit 2; }
printf '%s\n' "$1" | grep -Eq '^/data/projects/project-[0-9]+/(desks/employee|worktrees/task)-[0-9]+$' \
  || { echo "not a clone path: $1" >&2; exit 2; }
exec /bin/rm -rf --one-file-system -- "$1"
