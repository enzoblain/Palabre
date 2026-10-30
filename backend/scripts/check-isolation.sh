#!/bin/sh
# Checks the agent isolation inside the built image. Run as root in the container:
#   docker exec -u root [-e CHECK_GITHUB_REPO=owner/scratch-repo] <container> /srv/scripts/check-isolation.sh
# Prints one line per guarantee and exits non-zero if any is broken (or skipped).
# CHECK_POOL_ONLY=1 runs the checks of the agent1..N pool only (no GitHub repository needed): that is
# what the Compose smoke test runs in CI.
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

# sudo grants palabre exactly four rules, on the agent users and nobody else (root included)
pool="agent"
i=1; while [ "$i" -le "${AGENT_POOL_SIZE:-0}" ]; do pool="$pool,agent$i"; i=$((i + 1)); done
rules=$(sudo -l -U palabre | grep -E '^ *\(' | sed 's/^ *//')
cmds=$(printf '%s\n' "$rules" | sed 's/^([^)]*) *//; s/\(NOPASSWD\|PASSWD\|SETENV\|NOSETENV\): *//g' | tr ',' '\n' | sed 's/^ *//; s/ *$//' | grep .)
check "sudo -l shows exactly 4 rules for palabre" test "$(printf '%s\n' "$cmds" | grep -c .)" = 4
check "every rule runs as the pool users only ($pool)" test "$(printf '%s\n' "$rules" | sed 's/^(\([^)]*\)).*/\1/' | tr -d ' ' | sort -u)" = "$pool"
for cmd in '/home/palabre/.local/bin/claude' '/usr/bin/kill -KILL -- -[0-9]*' \
    '/usr/local/bin/palabre-rm-clone /data/projects/*' '/usr/local/bin/palabre-rm-clone /data/run/claude-*'; do
  check "sudo -l has the rule: $cmd" test "$(printf '%s\n' "$cmds" | grep -cxF -- "$cmd")" = 1
done
if [ "${AGENT_POOL_SIZE:-0}" -ge 1 ]; then
  denied "palabre cannot run anything else as agent1" as_palabre sudo -n -u agent1 /bin/true
fi

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
trap 'mv -f "$CLAUDE.real" "$CLAUDE"' EXIT
trap 'exit 130' INT TERM
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
  pair)
    # Two runs alive together: each looks at the other's process and MCP config. $2 dir, $3 me, $4 peer
    dir=$2; me=$3; peer=$4
    echo $$ > "$dir/$me.pid"; echo "$mcp" > "$dir/$me.mcp"
    i=0; while [ ! -s "$dir/$peer.mcp" ] && [ $i -lt 100 ]; do sleep 0.1; i=$((i + 1)); done
    if [ -s "$dir/$peer.mcp" ]; then found=found; else found=missing; fi
    other=$(cat "$dir/$peer.pid" 2>/dev/null); othermcp=$(cat "$dir/$peer.mcp" 2>/dev/null)
    out="uid=$(id -u)\npeer=$found"
    out="$out\nenviron=$(denied cat "/proc/$other/environ")\nmcpconfig=$(denied cat "$othermcp")"
    out="$out\nownenviron=$(if cat "/proc/$$/environ" >/dev/null 2>&1; then echo allowed; else echo denied; fi)"
    out="$out\nownmcp=$(if cat "$mcp" >/dev/null 2>&1; then echo ok; else echo denied; fi)"
    touch "$dir/$me.done"
    # Stay alive until the peer has looked too
    i=0; while [ ! -e "$dir/$peer.done" ] && [ $i -lt 100 ]; do sleep 0.1; i=$((i + 1)); done
    printf '{"session_id":"stub","result":"%s"}' "$out" ;;
  leave)
    setsid sleep 4242 </dev/null >/dev/null 2>&1 &
    sleep 1
    printf '{"session_id":"stub","result":"uid=%s\\nalive=%s"}' "$(id -u)" "$(pgrep -u "$(id -u)" -f 'sleep 4242' | wc -l)" ;;
  seen)
    printf '{"session_id":"stub","result":"uid=%s\\nalive=%s"}' "$(id -u)" "$(pgrep -u "$(id -u)" -f 'sleep 4242' | wc -l)" ;;
esac
STUB
chmod 755 "$CLAUDE"

run_as_palabre() { # script
  ( cd /srv && umask 002 && exec setpriv --reuid=palabre --regid=palabre --init-groups \
      env PATH="/home/palabre/.local/bin:$PATH" HOME=/home/palabre python "/srv/scripts/$1" )
}
[ "${CHECK_POOL_ONLY:-}" = 1 ] || run_as_palabre check_isolation_flow.py || fail=1
run_as_palabre check_isolation_pool.py || fail=1

exit $fail
