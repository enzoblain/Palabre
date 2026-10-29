#!/bin/sh
# Checks the agent isolation inside the built image. Run as root in the container:
#   docker exec -u root [-e CHECK_GITHUB_REPO=owner/scratch-repo] <container> /srv/scripts/check-isolation.sh
# Prints one line per guarantee and exits non-zero if any is broken (or skipped).
#
# THROWAWAY CONTAINER ONLY. For the runs it swaps the claude binary for a stub (restored on exit): use a throwaway
# container, not one whose orchestrator is running agents (see "Checking the isolation" in
# the README). CHECK_GITHUB_REPO names a scratch repository the backend's GitHub token can
# push to: the check clones it, commits as an agent, pushes, opens a PR and merges it.
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
if [ -n "$backend_pid" ]; then
  denied "agent cannot read the backend's environ" as_agent cat "/proc/$backend_pid/environ"
else
  echo "note no uvicorn in this container: the environ check runs on the probe process instead"
fi
denied "agent cannot list runtime/" as_agent ls "$DATA/runtime"
denied "agent cannot read the backend's home" as_agent ls /home/palabre
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

# Agent runs through the real runner, with a stub instead of claude: it reports what the
# agent can see and do from inside the run (stdout is claude's JSON result)
CLAUDE=/home/palabre/.local/bin/claude
mv "$CLAUDE" "$CLAUDE.real"
trap 'mv -f "$CLAUDE.real" "$CLAUDE"' EXIT INT TERM
cat > "$CLAUDE" <<'STUB'
#!/bin/sh
# $2 is the prompt: "probe <cwd> <reference> <pids...>", "commit <dir>" or "hang"
prev=
for arg in "$@"; do [ "$prev" = --mcp-config ] && mcp=$arg; prev=$arg; done
set -- $2
mode=$1
denied() { if "$@" >/dev/null 2>&1; then echo allowed; else echo denied; fi; }
case $mode in
  probe)
    cwd=$2; ref=$3; shift 3
    environ=denied
    for pid in "$@"; do cat "/proc/$pid/environ" >/dev/null 2>&1 && environ=allowed; done
    out="uid=$(id -u)\npath=$PATH\nhome=$HOME\nenviron=$environ"
    out="$out\nsecrets=$(env | grep -c -E 'GITHUB_TOKEN|ADMIN_TOKEN|DATABASE_URL|POSTGRES_PASSWORD|CLAUDE_CODE_OAUTH_TOKENS')"
    out="$out\nreference=$(denied ls "$ref")\nruntime=$(denied ls /data/runtime)"
    out="$out\nsecretsdir=$(denied cat /run/palabre-secrets/github_token)"
    out="$out\ncwdwrite=$(if touch "$cwd/.probe" 2>/dev/null; then echo ok; else echo denied; fi)"
    out="$out\nmcpconfig=$(if [ -r "$mcp" ]; then echo ok; else echo denied; fi)"
    printf '{"session_id":"stub","result":"%s"}' "$out" ;;
  commit)
    cd "$2" && echo "checked" > check-isolation.txt && git add check-isolation.txt \
      && git commit -q -m "test(isolation): end-to-end check" && ok=ok || ok=failed
    printf '{"session_id":"stub","result":"commit=%s"}' "$ok" ;;
  hang)
    sleep 600 & sleep 600 ;;
esac
STUB
chmod 755 "$CLAUDE"

( cd /srv && umask 002 && exec setpriv --reuid=palabre --regid=palabre --init-groups \
    env PATH="/home/palabre/.local/bin:$PATH" HOME=/home/palabre python /srv/scripts/check_isolation_flow.py ) || fail=1

exit $fail
