#!/bin/sh
# Empties one desk or task clone as the agent user (#130): files the agent created outside the
# shared group cannot be removed by the backend. The clone's own directory is left to the
# backend, which owns the directory holding it. Installed root-owned, run through a sudo rule.
# Only the exact shape of a clone path is accepted, so the rule is not a general rm.
set -eu
[ "$#" -eq 1 ] || { echo "usage: rm-clone <clone path>" >&2; exit 2; }
# No newline, dot or other odd character: the pattern below then matches the whole argument
case "$1" in
  *[!A-Za-z0-9/_-]*) echo "not a clone path: $1" >&2; exit 2 ;;
esac
printf '%s\n' "$1" | grep -Eq '^/data/projects/project-[0-9]+/(desks/employee|worktrees/task)-[0-9]+$' \
  || { echo "not a clone path: $1" >&2; exit 2; }
[ -d "$1" ] && [ ! -L "$1" ] || { echo "not a directory: $1" >&2; exit 2; }
# -P: never follow symlinks
exec /usr/bin/find -P "$1" -xdev -mindepth 1 -delete
