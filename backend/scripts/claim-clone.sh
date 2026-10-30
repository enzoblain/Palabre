#!/bin/sh
# Hands a desk or task clone (or an employee's Go cache) to the agent account that is about to run in it (#160):
# owner and group become the account and its primary group (its private one), nobody else can write or read it.
# Runs as root through a sudo rule, and only before the run starts (the account's processes
# of the previous run are dead). Only the exact shape of those paths and of an agent account is accepted.
set -eu
[ "$#" -eq 2 ] || { echo "usage: claim-clone <clone path> <agent account>" >&2; exit 2; }
# No newline, dot or other odd character: the patterns below then match the whole argument
case "$1$2" in
  *[!A-Za-z0-9/_-]*) echo "bad argument" >&2; exit 2 ;;
esac
printf '%s\n' "$1" | grep -Eq '^/data/projects/project-[0-9]+/(desks/employee|worktrees/task)-[0-9]+$|^/data/toolchains/gopath/employee-[0-9]+$' \
  || { echo "not a clone path: $1" >&2; exit 2; }
printf '%s\n' "$2" | grep -Eq '^agent[0-9]*$' || { echo "not an agent account: $2" >&2; exit 2; }
[ -d "$1" ] && [ ! -L "$1" ] || { echo "not a directory: $1" >&2; exit 2; }
group=$(id -gn "$2")
# -P and -h: never follow a symlink. A file with several links may point outside the clone: left alone.
/usr/bin/find -P "$1" -xdev \( -type f -links +1 \) -prune -o -exec chown -h "$2:$group" {} +
/usr/bin/find -P "$1" -xdev -type d -exec chmod u+rwx,g+rwxs,o-rwx {} +
/usr/bin/find -P "$1" -xdev -type f -links 1 -exec chmod u+rw,g+rw,o-rwx,ug-s {} +
