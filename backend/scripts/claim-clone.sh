#!/bin/sh
# Hands a desk or task clone (or an employee's Go cache) to the agent account that is about to run in it (#160):
# owner and group become the account and its primary group (its private one), nobody else can write or read it.
# With "palabre" as account it takes the clone back after the run. Runs as root through a sudo rule, only
# while no process of the previous owner is alive. Only the exact shape of those paths and of a pool account is accepted.
set -eu
[ "$#" -eq 2 ] || { echo "usage: claim-clone <clone path> <agent account>" >&2; exit 2; }
# No newline, dot or other odd character: the patterns below then match the whole argument
case "$1$2" in
  *[!A-Za-z0-9/_-]*) echo "bad argument" >&2; exit 2 ;;
esac
printf '%s\n' "$1" | grep -Eq '^/data/projects/project-[0-9]+/(desks/employee|worktrees/task)-[0-9]+$|^/data/toolchains/gopath/employee-[0-9]+$' \
  || { echo "not a clone path: $1" >&2; exit 2; }
printf '%s\n' "$2" | grep -Eq '^(agent[0-9]+|palabre)$' || { echo "not a pool account: $2" >&2; exit 2; }
[ -d "$1" ] && [ ! -L "$1" ] || { echo "not a directory: $1" >&2; exit 2; }
group=$(id -gn "$2")
# -R walks with fts (openat): no symlink is followed, whatever the clone's previous owner swaps meanwhile.
# The tree is only ever one of palabre or of an account whose processes are all dead.
/usr/bin/chown -R -h "$2:$group" "$1"
if [ "$2" = palabre ]; then
  /usr/bin/chmod -R u+rwX,go-rwx,ug-s "$1"
else
  /usr/bin/chmod -R u+rwX,g+rwX,o-rwx,ug-s "$1"
  # Setgid directories: what the backend creates in the clone during the run (git fetch on submit)
  # stays in the account's group, so the run can still write it. Nothing of the account lives here yet.
  /usr/bin/find -P "$1" -type d -exec /usr/bin/chmod g+s {} +
fi
