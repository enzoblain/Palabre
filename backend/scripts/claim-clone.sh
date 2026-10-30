#!/bin/sh
# Hands a desk or task clone (or an employee's Go cache) to the agent account that is about to run in it (#160):
# owner and group become the account and its primary group (its private one), nobody else can write or read it.
# With "palabre" as account it takes the clone back after the run. Runs as root through a sudo rule, only
# while no process of the previous owner is alive. Only the exact shape of those paths and of a pool account is accepted.
# The projects root is written root-owned at image build (PROJECTS_DIR), never taken from the caller's environment: a missing or odd root refuses everything.
set -eu
CONF="${PALABRE_PROJECTS_CONF:-/etc/palabre/projects-dir.conf}"
ROOT=$(cat "$CONF" 2>/dev/null) || { echo "no projects root configured" >&2; exit 2; }
case "$ROOT" in
  /*[!A-Za-z0-9/_-]*|*/|/|"") echo "bad projects root: $ROOT" >&2; exit 2 ;;
  /*) ;;
  *) echo "bad projects root: $ROOT" >&2; exit 2 ;;
esac
[ "$#" -eq 2 ] || { echo "usage: claim-clone <clone path> <agent account>" >&2; exit 2; }
# No newline, dot or other odd character: the patterns below then match the whole argument
case "$1$2" in
  *[!A-Za-z0-9/_-]*) echo "bad argument" >&2; exit 2 ;;
esac
printf '%s\n' "$1" | grep -Eq "^$ROOT/project-[0-9]+/(desks/employee|worktrees/task)-[0-9]+\$|^/data/toolchains/gopath/employee-[0-9]+\$" \
  || { echo "not a clone path: $1" >&2; exit 2; }
printf '%s\n' "$2" | grep -Eq '^(agent[0-9]+|palabre)$' || { echo "not a pool account: $2" >&2; exit 2; }
[ -d "$1" ] && [ ! -L "$1" ] || { echo "not a directory: $1" >&2; exit 2; }
group=$(id -gn "$2")
if [ "$2" != palabre ]; then
  # Refuse a tree holding something of another account (a leftover of a run that was not handed back)
  # or a hard-linked non-directory (it could alias a file outside the clone): the chown would hand it over.
  odd=$(/usr/bin/find -P "$1" \( ! -user palabre ! -user "$2" \) -print -quit -o ! -type d -links +1 -print -quit)
  [ -z "$odd" ] || { echo "refusing to claim: unexpected owner or hard link in the tree" >&2; exit 3; }
fi
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
