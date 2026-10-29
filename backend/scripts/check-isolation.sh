#!/bin/sh
# Checks the agent isolation inside the built image. Run as root in the container:
#   docker exec -u root <container> /srv/scripts/check-isolation.sh
# Exits non-zero at the first broken guarantee.
set -u

DATA=/data
fail=0
as_agent() { setpriv --reuid=agent --regid=agent --init-groups "$@"; }
as_palabre() { setpriv --reuid=palabre --regid=palabre --init-groups "$@"; }
check() { # description, then a command that must succeed
  desc=$1; shift
  if "$@" >/dev/null 2>&1; then echo "ok   $desc"; else echo "FAIL $desc"; fail=1; fi
}
denied() { desc=$1; shift; if "$@" >/dev/null 2>&1; then echo "FAIL $desc"; fail=1; else echo "ok   $desc"; fi; }

backend_pid=$(pgrep -u palabre -f uvicorn | head -n 1)
denied "agent cannot read the backend's environ" as_agent cat "/proc/$backend_pid/environ"
denied "agent cannot list runtime/" as_agent ls "$DATA/runtime"
denied "agent cannot read the backend's home" as_agent ls /home/palabre/.local
for repo in "$DATA"/projects/project-*/repo; do
  [ -d "$repo" ] || continue
  denied "agent cannot read $repo" as_agent test -r "$repo/config"
  denied "agent cannot write in $repo" as_agent touch "$repo/x"
done
check "agent can cross /data/run" as_agent test -x "$DATA/run"
denied "agent cannot list /data/run" as_agent ls "$DATA/run"

check "sudo keeps claude in sudo's process group (!use_pty)" sh -c "sudo -l -U palabre | grep -q '!use_pty'"
denied "palabre cannot run anything else as agent" as_palabre sudo -n -u agent /bin/true
denied "palabre cannot become root" as_palabre sudo -n -u root /bin/true

# The kill rule stops a whole process group of the agent, children included
as_agent setsid sh -c 'sleep 600 & sleep 600' &
sleep 1
pgid=$(pgrep -u agent -x sleep | head -n 1 | xargs -I{} ps -o pgid= -p {} | tr -d ' ')
as_palabre sudo -n -u agent /usr/bin/kill -KILL -- "-$pgid"
sleep 1
denied "no agent process is left after the group kill" pgrep -u agent -x sleep

exit $fail
