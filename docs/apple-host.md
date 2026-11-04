# Mac builder

The small program that runs on the Mac and builds the Apple jobs. The structure and the security rules are in
[Apple mode](apple-mode.md); this page is how to install, run and roll back the worker. Code: `deploy/apple-host/`.

## What it does

The worker (`worker.py`, standard library only) polls the backend (`POST /api/apple-host/claim`). For each job it:

1. clones the pinned image into a new VM `job-<id>` (`tart clone`), starts it without window or shared folder;
2. runs `/usr/local/bin/palabre-job-runner <backend_url> <job_id> <source_url> <commit_sha>` in the VM with
   `tart exec`. The one-time job token goes through the standard input of that command, never in the arguments. The runner
   (part of the image) downloads the source, runs `swift build` and `swift test`, and exits `0` (passed), `10`
   (build or tests broken) or anything else (infra problem);
3. deletes the VM, in every case (error, crash, time limit), then posts the verdict: `0` is `passed`, `10` is `failed`,
   a time limit, a crashed VM, a failed clone or any other exit code is `error` (infra).

Before the job, the worker probes the guest with a harmless command (`/usr/bin/true`) until `tart exec` answers, so a job
that fails is never mistaken for a guest that is not ready and never runs twice. `job_timeout_seconds` covers the probe
and the job, not `tart clone` and the VM start. The VM is always deleted: if `tart stop` hangs, `tart delete` still runs.

At most `max_vms` jobs run at once (2 at most, Apple's limit); a free slot is needed before a job is claimed, so
the next jobs wait in the backend's queue. At start, every leftover `job-*` VM is deleted. The log sent back is the
tail of the output, with the job token removed. VM calls are all in `vm.py`, so changing the tool (plan B: UTM) means rewriting that file only.

Only the builder token is on the Mac, in a file the worker refuses to read if others can read it. The VM only
gets the job token.

## Install, step by step

On the Mac (Apple silicon), as an administrator:

1. Create a standard (non-admin) user `palabre`. System Settings, Energy: no automatic sleep. Firewall on.
2. Install Tart: `brew install cirruslabs/cli/tart`.
3. In the Palabre app (or with the admin token), register the Mac: `POST /api/apple-hosts {"name": "mac-enzo"}`. The answer
   holds the `pmac_...` token, shown once.
4. Save the token: `sudo install -m 600 -o palabre /dev/null /etc/palabre-apple-worker.token`, then paste it in that file.
5. Pull the image as the worker user: `sudo -u palabre tart pull <image@sha256:...>` (the digest set as `APPLE_IMAGE` on the server).
6. Write `/etc/palabre-apple-worker.toml` (no secret in it):

   ```toml
   backend_url = "https://palabre.example.com"
   token_file = "/etc/palabre-apple-worker.token"
   image = "ghcr.io/example/macos-xcode@sha256:<64 hex>"
   max_vms = 2
   job_timeout_seconds = 1800
   # net_args = ["--net-softnet", "--net-softnet-block=10.0.0.0/8"]  # see apple-mode.md, network isolation
   ```

7. From a copy of the repository, run `cd deploy/apple-host && sudo ./install.sh`. It copies the worker to
   `/usr/local/lib/palabre-apple-worker`, installs the launchd daemon (starts at boot, restarted on failure) and starts it.

Check: `tail -f /var/log/palabre-apple-worker.log`, and the Mac shows as connected in the app.
Upgrade the worker: pull the repository and run `sudo ./install.sh` again (it is idempotent).

## Tests

`cd deploy/apple-host && python3 -m unittest test_worker` : the queue limit, timeouts, cleanup and verdicts, with a
fake VM tool and a fake backend (no Mac needed).

## Known limit: no GUI session

Virtualization.framework may refuse to boot macOS guests without a logged-in GUI session, and a LaunchDaemon has none.
Not validated on the real Mac yet. If `tart run` fails from the daemon, use a LaunchAgent instead: put the plist in
`/Users/palabre/Library/LaunchAgents/`, enable automatic login for `palabre`, and load it with
`launchctl bootstrap gui/<uid> <plist>`. Roll back the same way with `launchctl bootout gui/<uid> <plist>`.

## Roll back

- Stop the worker: `sudo launchctl bootout system /Library/LaunchDaemons/com.palabre.apple-worker.plist`, and remove that file
  and `/usr/local/lib/palabre-apple-worker` to uninstall. Leftover VMs: `tart list`, then `tart delete job-<id>`.
- Revoke the token: `DELETE /api/apple-hosts/{id}`.
- Previous image: put the previous digest in the config file (and in `APPLE_IMAGE`), then `sudo ./install.sh`.
