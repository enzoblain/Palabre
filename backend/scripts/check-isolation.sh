#!/bin/sh
# Checks the agent isolation inside the built image. Run as root in the container:
#   docker exec -u root [-e CHECK_GITHUB_REPO=owner/scratch-repo] <container> /srv/scripts/check-isolation.sh
# Prints one line per guarantee and exits non-zero if any is broken (or skipped).
# CHECK_POOL_ONLY=1 skips the GitHub flow and runs the checks that need no GitHub repository (the agent1..N pool, the legacy shared-account upload-pack): that is
# what the Compose smoke test runs in CI.
#
# THROWAWAY CONTAINER ONLY. For the runs it swaps the claude binary for a stub (restored on exit): use a throwaway
# container, not one whose orchestrator is running agents (see "Checking the isolation" in
# the README). CHECK_GITHUB_REPO names a scratch repository the backend's GitHub token can
# push to: the check clones it, commits as an agent, pushes, opens a PR and merges it.
set -u

DATA=/data
# The projects root the image was built with: the same file the root-owned scripts read
PROJECTS=$(cat /etc/palabre/projects-root.conf 2>/dev/null)
case "$PROJECTS" in /?*) ;; *) echo "::error::no projects root in /etc/palabre/projects-root.conf"; exit 1 ;; esac
fail=0
# The agent has no group of its own (useradd --gid work): --regid=agent would fail before running the command
as_agent() { setpriv --reuid=agent --regid=work --init-groups "$@"; }
as_palabre() { setpriv --reuid=palabre --regid=palabre --init-groups "$@"; }
check() { # description, then a command that must succeed
  desc=$1; shift
  if "$@" >/dev/null 2>&1; then echo "ok   $desc"; else echo "FAIL $desc"; echo "::error::$desc: command failed: $*"; fail=1; fi
}
denied() {
  desc=$1; shift
  if "$@" >/dev/null 2>&1; then echo "FAIL $desc"; echo "::error::$desc: expected a refusal, but this succeeded: $*"; fail=1; else echo "ok   $desc"; fi
}

# Positive control first: a broken as_agent must fail loudly instead of turning every "denied" into a pass
[ "$(as_agent id -un 2>/dev/null)" = agent ] && echo "ok   as_agent really runs as agent" \
  || { echo "FAIL as_agent really runs as agent"; echo "::error::as_agent really runs as agent: expected id -un = agent; got: $(as_agent id 2>&1 | tr '\n' ' ')"; fail=1; }

backend_pid=$(pgrep -u palabre -f uvicorn | head -n 1)
if [ -n "$backend_pid" ]; then
  denied "agent cannot read the backend's environ" as_agent cat "/proc/$backend_pid/environ"
else
  echo "note no uvicorn in this container: the environ check runs on the probe process instead"
fi
denied "agent cannot list runtime/" as_agent ls "$DATA/runtime"
denied "agent cannot read the backend's home" as_agent ls /home/palabre
for repo in "$PROJECTS"/project-*/repo; do
  [ -d "$repo" ] || continue
  denied "agent cannot read $repo" as_agent test -r "$repo/config"
  denied "agent cannot write in $repo" as_agent touch "$repo/x"
done
# Not "agent can cross /data/run" alone: a broken as_agent would make every denied below pass for nothing
check "agent can cross /data/run" as_agent test -x "$DATA/run"
denied "agent cannot list /data/run" as_agent ls "$DATA/run"

check "sudo keeps claude in sudo's process group (!use_pty)" sh -c "sudo -l -U palabre | grep -q '!use_pty'"
denied "palabre cannot run anything else as agent" as_palabre sudo -n -u agent /bin/true
denied "palabre cannot become root" as_palabre sudo -n -u root /bin/true

# sudo grants palabre exactly four rules, on the agent users and nobody else (root included).
# `sudo -ll` prints one command per line (the short form wraps long lines and merges rules), and the
# expected users come from the image itself (getent), not from the runtime AGENT_POOL_SIZE.
pool=$(getent passwd | cut -d: -f1 | grep -E '^agent[0-9]*$' | sort | tr '\n' ',' | sed 's/,$//')
raw=$(sudo -ll -U palabre 2>&1)
# One "runas|setenv|command" line per command
rules=$(printf '%s\n' "$raw" | awk '
  /^ *RunAsUsers:/ { sub(/^ *RunAsUsers: */, ""); gsub(/ /, ""); runas = $0; setenv = 0; next }
  /^ *Options:/ { setenv = ($0 ~ /(^|[ ,])setenv/) ? 1 : 0; next }
  /^ *Commands:/ { incmd = 1; next }
  /^Sudoers entry:/ { incmd = 0; next }
  incmd && NF { sub(/^[ \t]*/, ""); sub(/[ \t]*$/, ""); print runas "|" setenv "|" $0 }')
fail_with() { # description, got, expected
  echo "FAIL $1"; fail=1
  printf '::error::%s: got [%s], expected [%s]\n' "$1" "$2" "$3"
  printf '::error::sudo -ll -U palabre said: %s\n' "$(printf '%s' "$raw" | tr '\n' '~')"
}
expect() { # description, got, expected
  if [ "$2" = "$3" ]; then echo "ok   $1"; else fail_with "$1" "$2" "$3"; fi
}
cmds=$(printf '%s\n' "$rules" | cut -d'|' -f3-)
expect "sudo -l shows exactly 9 rules for palabre" "$(printf '%s\n' "$rules" | grep -c .)" 9
norm() { tr ',' '\n' | grep . | sort | tr '\n' ' '; }
expect "every rule runs as the pool users or root ($pool,root)" "$(printf '%s\n' "$rules" | cut -d'|' -f1 | sort -u | norm)" "$(printf '%s,root' "$pool" | norm)"
for cmd in '/home/palabre/.local/bin/claude' '/usr/bin/kill -KILL -- -[0-9]*' \
    "/usr/local/bin/palabre-rm-clone $PROJECTS/*" '/usr/local/bin/palabre-rm-clone /data/run/claude-*' "/usr/local/bin/palabre-upload-pack $PROJECTS/*" \
    "/usr/local/bin/palabre-claim-clone $PROJECTS/* agent*" '/usr/local/bin/palabre-claim-clone /data/toolchains/gopath/* agent*' \
    "/usr/local/bin/palabre-claim-clone $PROJECTS/* palabre" '/usr/local/bin/palabre-claim-clone /data/toolchains/gopath/* palabre'; do
  expect "sudo -l has the rule: $cmd" "$(printf '%s\n' "$cmds" | grep -cxF -- "$cmd")" 1
done
# The only rules running as root are the four claim-clone ones
expect "the root rules are the 4 claim-clone ones only" "$(printf '%s\n' "$rules" | grep '^root|' | cut -d'|' -f3 | grep -c '^/usr/local/bin/palabre-claim-clone ')" 4
expect "no other rule runs as root" "$(printf '%s\n' "$rules" | grep -c '^root|')" 4
expect "SETENV is on the claude rule only" "$(printf '%s\n' "$rules" | grep '|1|' | cut -d'|' -f3 | tr '\n' ' ')" "/home/palabre/.local/bin/claude "
for user in $(printf '%s' "$pool" | tr ',' ' '); do
  [ "$user" = agent ] && continue
  denied "palabre cannot run anything else as $user" as_palabre sudo -n -u "$user" /bin/true
done

# Kill path 1, end of a run or timeout (runner.py:172): sudo -n -u agent /usr/bin/kill -KILL -- -PGID, sent by palabre.
# Live agent processes: a zombie (state Z) is a dead process nobody reaped yet, not something still running
agent_sleeps() { ps -u agent -o pid=,stat=,comm= | awk '$3 == "sleep" && $2 !~ /^Z/ {print $1}'; }
as_agent setsid sh -c 'sleep 600 & sleep 600' &
sleep 1
sleep_pid=$(agent_sleeps | head -n 1)
pgid=$(ps -o pgid= -p "${sleep_pid:-0}" 2>/dev/null | tr -d ' ')
before=$(ps -o pid,pgid,sid,stat,user,args -u agent 2>&1 | tr '\n' '~')
check "the agent sleeps were started" test -n "$sleep_pid"
check "the agent group to kill exists" test -n "$pgid"
as_palabre sudo -n -u agent /usr/bin/kill -KILL -- "-${pgid:-0}"
kill_rc=$?
expect "the group kill succeeded" "$kill_rc" 0
# SIGKILL is immediate, but the reaping is not: wait up to 3 s, and still require zero live process at the end
for _ in 1 2 3 4 5 6; do [ -z "$(agent_sleeps)" ] && break; sleep 0.5; done
after=$(ps -o pid,pgid,sid,stat,user,args -u agent 2>&1 | tr '\n' '~')
if [ -z "$(agent_sleeps)" ]; then echo "ok   no agent process is left after the group kill"
else
  echo "FAIL no agent process is left after the group kill"
  echo "::error::no agent process is left after the group kill: target pgid=$pgid kill_rc=$kill_rc; before: $before; after: $after"
  fail=1
fi

# Kill path 2, release of an account (agent_pool.kill_all, agent_pool.py:125): kill -KILL -- -1 signals every process of
# the uid, also those in another session (setsid) and so outside any process group the runner knows about.
as_agent setsid sleep 601 </dev/null >/dev/null 2>&1 &
sleep 1
agent_live() { ps -u agent -o pid=,stat=,args= | awk '$2 !~ /^Z/ && $3 == "sleep" && $4 == "601" {print $1}'; }
check "a setsid process of the agent is running" test -n "$(agent_live)"
before=$(ps -o pid,pgid,sid,stat,user,args -u agent 2>&1 | tr '\n' '~')
as_palabre sudo -n -u agent /usr/bin/kill -KILL -- -1
kill_rc=$?
expect "the kill_all kill succeeded" "$kill_rc" 0
for _ in 1 2 3 4 5 6; do [ -z "$(agent_live)" ] && break; sleep 0.5; done
after=$(ps -o pid,pgid,sid,stat,user,args -u agent 2>&1 | tr '\n' '~')
if [ -z "$(agent_live)" ] && [ -z "$(ps -u agent -o stat= | grep -v '^Z')" ]; then echo "ok   no live agent process is left after kill -1 (kill_all)"
else
  echo "FAIL no live agent process is left after kill -1 (kill_all)"
  echo "::error::no live agent process is left after kill -1 (kill_all): kill_rc=$kill_rc; before: $before; after: $after"
  fail=1
fi

# Agent runs through the real runner, with a stub instead of claude: it reports what the
# agent can see and do from inside the run (stdout is claude's JSON result)
CLAUDE=/home/palabre/.local/bin/claude
mv "$CLAUDE" "$CLAUDE.real"
# POSIX sh has no ERR trap: on exit, a non-zero status that no FAIL line explains is reported here
on_exit() {
  rc=$?
  mv -f "$CLAUDE.real" "$CLAUDE"
  if [ "$rc" -ne 0 ] && [ "$fail" -eq 0 ]; then
    echo "FAIL unexpected exit (rc=$rc) before any check failed"
    echo "::error::check-isolation.sh exited unexpectedly with rc=$rc without a failed check"
  fi
}
trap on_exit EXIT
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
    # A refusal must come from the permissions, not from a file that is not there
    if [ -e "$othermcp" ]; then mcpthere=yes; else mcpthere=missing; fi
    out="uid=$(id -u)\npeer=$found"
    out="$out\nenviron=$(denied cat "/proc/$other/environ")\nmcpconfig=$(denied cat "$othermcp")\nmcpthere=$mcpthere"
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

# Restart of the entrypoint, shared account (AGENT_POOL_SIZE=0): the existing clones go to group work, so the one agent can
# still write in them (and serve them to upload-pack); with a pool they stay palabre:palabre go-rwx until claimed.
restart_clone=$DATA/projects/project-99997/worktrees/task-2
mkdir -p "$restart_clone"
chown palabre:palabre "$restart_clone"
as_palabre git init -q "$restart_clone"
as_palabre git -C "$restart_clone" -c user.name=t -c user.email=t@t commit -q --allow-empty -m restart
as_palabre git -C "$restart_clone" update-ref refs/heads/task/2 HEAD
chmod -R go-rwx "$restart_clone"
check "entrypoint restart (shared account)" env AGENT_POOL_SIZE=0 docker-entrypoint.sh true
check "shared account: after a restart agent can write in an existing clone" as_agent touch "$restart_clone/.git/hooks/pre-commit"
restart_scratch=$(mktemp -d) && chown palabre:palabre "$restart_scratch" && as_palabre git init -q "$restart_scratch"
check "shared account: after a restart agent can serve the clone to palabre-upload-pack" \
  as_palabre git -C "$restart_scratch" fetch -q --no-tags --upload-pack="sudo -n -u agent /usr/local/bin/palabre-upload-pack" "$restart_clone" refs/heads/task/2:refs/heads/task/2
# Back to a pool: the clone that was shared is taken back
check "entrypoint restart (pool)" env AGENT_POOL_SIZE=8 docker-entrypoint.sh true
denied "pool mode: a restart takes back a shared clone" as_agent test -r "$restart_clone/.git/config"

# A claimed clone and Go cache belong to one account alone (#160): through the real sudo rule, as the backend does
as_pool_sh() { u=$1; shift; setpriv --reuid="$u" --regid="$u" --init-groups "$@"; }
claim_root=$DATA/projects/project-99997/worktrees/task-1
gocache=$DATA/toolchains/gopath/employee-99997
mkdir -p "$claim_root" "$gocache"
chown palabre:palabre "$DATA/projects/project-99997" "$DATA/projects/project-99997/worktrees" "$claim_root" "$gocache"
as_palabre git init -q "$claim_root"
for target in "$claim_root" "$gocache"; do
  check "palabre can claim $target for agent1" as_palabre sudo -n /usr/local/bin/palabre-claim-clone "$target" agent1
done
check "agent1 can write a hook in its claimed clone" as_pool_sh agent1 touch "$claim_root/.git/hooks/pre-commit"
check "agent1 can write the git config of its claimed clone" as_pool_sh agent1 sh -c "echo >> '$claim_root/.git/config'"
check "agent1 can write in its claimed Go cache" as_pool_sh agent1 touch "$gocache/x"
denied "agent2 cannot plant a hook in agent1's clone" as_pool_sh agent2 touch "$claim_root/.git/hooks/post-commit"
denied "agent2 cannot overwrite agent1's hook" as_pool_sh agent2 sh -c "echo x >> '$claim_root/.git/hooks/pre-commit'"
denied "agent2 cannot write the git config of agent1's clone" as_pool_sh agent2 sh -c "echo x >> '$claim_root/.git/config'"
denied "agent2 cannot write in agent1's Go cache" as_pool_sh agent2 touch "$gocache/y"
# Reassignment (#160): the run ends, the clone goes back to palabre, then to another account
for target in "$claim_root" "$gocache"; do
  check "palabre can take $target back" as_palabre sudo -n /usr/local/bin/palabre-claim-clone "$target" palabre
done
denied "agent1 cannot write a hook once the clone is released" as_pool_sh agent1 touch "$claim_root/.git/hooks/post-merge"
denied "agent1 cannot write the git config once the clone is released" as_pool_sh agent1 sh -c "echo x >> '$claim_root/.git/config'"
denied "agent1 cannot write in the Go cache once released" as_pool_sh agent1 touch "$gocache/z"
for target in "$claim_root" "$gocache"; do
  check "palabre can claim $target for agent2" as_palabre sudo -n /usr/local/bin/palabre-claim-clone "$target" agent2
done
check "agent2 can write a hook in its claimed clone" as_pool_sh agent2 touch "$claim_root/.git/hooks/post-commit"
denied "agent1 cannot write a hook in the clone now claimed by agent2" as_pool_sh agent1 touch "$claim_root/.git/hooks/post-rewrite"
denied "agent1 cannot write the git config of agent2's clone" as_pool_sh agent1 sh -c "echo x >> '$claim_root/.git/config'"
denied "agent1 cannot write in agent2's Go cache" as_pool_sh agent1 touch "$gocache/w"
# A claim refuses a tree with a file of another account, or a hard link (#160)
as_palabre sudo -n /usr/local/bin/palabre-claim-clone "$claim_root" palabre
touch "$claim_root/foreign"; chown agent2:agent2 "$claim_root/foreign"
denied "claim for agent1 refuses a file owned by agent2" as_palabre sudo -n /usr/local/bin/palabre-claim-clone "$claim_root" agent1
chown palabre:palabre "$claim_root/foreign"; ln "$claim_root/foreign" "$claim_root/alias"
denied "claim for agent1 refuses a hard-linked file" as_palabre sudo -n /usr/local/bin/palabre-claim-clone "$claim_root" agent1
# The push fetch reads a task clone as the account owning it (#193): an alternates entry pointing at another
# project's objects (private to palabre) gets nothing served, whatever the denylist would say
victim=$DATA/projects/project-99996/repo
mkdir -p "$victim" && chown palabre:palabre "$DATA/projects/project-99996" "$victim" && chmod 700 "$victim"
as_palabre git init -q "$victim"
as_palabre git -C "$victim" -c user.name=t -c user.email=t@t commit -q --allow-empty -m secret
secret=$(as_palabre git -C "$victim" rev-parse HEAD)
rm -f "$claim_root/foreign" "$claim_root/alias"
as_palabre git -C "$claim_root" -c user.name=t -c user.email=t@t commit -q --allow-empty -m legit
legit=$(as_palabre git -C "$claim_root" rev-parse HEAD)
as_palabre git -C "$claim_root" update-ref refs/heads/task/1 "$legit"
as_palabre sudo -n /usr/local/bin/palabre-claim-clone "$claim_root" agent1
UP="sudo -n -u agent1 /usr/local/bin/palabre-upload-pack"
scratch=$(mktemp -d) && chown palabre:palabre "$scratch" && as_palabre git init -q "$scratch"
# Positive control: also proves the sudoers rule matches what git invokes
check "the upload-pack as agent1 serves the clone's own commit" \
  as_palabre git -C "$scratch" fetch -q --no-tags --upload-pack="$UP" "$claim_root" refs/heads/task/1:refs/heads/task/1
check "the legit commit reached the scratch repo" as_palabre git -C "$scratch" cat-file -e "$legit"
# Alternates to the victim, and a ref (written as root) naming its commit
echo "$victim/.git/objects" > "$claim_root/.git/objects/info/alternates"
echo "$secret" > "$claim_root/.git/refs/heads/task/1"
scratch2=$(mktemp -d) && chown palabre:palabre "$scratch2" && as_palabre git init -q "$scratch2"
denied "the upload-pack as agent1 cannot serve another project through alternates" \
  as_palabre git -C "$scratch2" fetch -q --no-tags --upload-pack="$UP" "$claim_root" refs/heads/task/1:refs/heads/task/1
denied "the other project's commit did not reach the scratch repo" as_palabre git -C "$scratch2" cat-file -e "$secret"
rm -rf "$scratch" "$scratch2"
denied "palabre cannot upload-pack a path that is not a task clone" as_palabre sudo -n -u agent1 /usr/local/bin/palabre-upload-pack "$victim"
rm -rf "$DATA/projects/project-99996"
rm -rf "$DATA/projects/project-99997" "$gocache"

run_as_palabre() { # script; a crash (traceback on stderr, no FAIL line) is reported as a FAIL with its last lines
  err=$(mktemp) || { echo "FAIL cannot create a temp file for $1"; echo "::error::cannot create a temp file for $1"; return 1; }
  ( cd /srv && umask 002 && exec setpriv --reuid=palabre --regid=palabre --init-groups \
      env PYTHONPATH=/srv PATH="/home/palabre/.local/bin:$PATH" HOME=/home/palabre python "/srv/scripts/$1" ) 2>"$err"
  rc=$?
  cat "$err" >&2
  if [ "$rc" -ne 0 ]; then
    echo "FAIL $1 exited with rc=$rc"
    echo "::error::$1 exited with rc=$rc; last stderr lines: $(tail -n 20 "$err" | tr '\n' '~')"
  fi
  rm -f "$err"
  return "$rc"
}
[ "${CHECK_POOL_ONLY:-}" = 1 ] || run_as_palabre check_isolation_flow.py || fail=1
run_as_palabre check_isolation_pool.py || fail=1
# Outside the pool-only gate on purpose: the legacy shared-account mode must stay covered by the CI smoke
run_as_palabre check_isolation_legacy.py || fail=1

exit $fail
