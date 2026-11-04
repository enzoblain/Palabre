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
that fails is never mistaken for a guest that is not ready and never runs twice. `job_timeout_seconds` starts after `tart clone`
and the VM start, and covers the boot probe and the job. The VM is always deleted: if `tart stop` hangs, `tart delete` still runs.

At most `max_vms` jobs run at once (2 at most, Apple's limit); a free slot is needed before a job is claimed, so
the next jobs wait in the backend's queue. At start, every leftover `job-*` VM is deleted. The log sent back is the
tail of the output, with the job token removed. VM calls are all in `vm.py`, so changing the tool (plan B: UTM) means rewriting that file only.

Only the builder token is on the Mac, in a file the worker refuses to read if others can read it. The VM only
gets the job token.

## Install, step by step

On the Mac (Apple silicon), as an administrator:

1. Create a standard (non-admin) user `palabre`. System Settings, Energy: no automatic sleep. Firewall on.
2. Install Tart: `brew install cirruslabs/cli/tart`. The worker needs `--net-softnet-block`, so use Tart 2.16.0 or newer
   (to my knowledge the first release with `--net-softnet-allow` and `--net-softnet-block`; check that `tart run --help` lists
   `--net-softnet-block`).
3. Register the Mac with a one-time enrollment code. An admin generates it (`POST /api/apple-enrollment-codes`, answer
   `penr_...`, shown once, valid `APPLE_ENROLLMENT_CODE_TTL_SECONDS`, 15 minutes by default). Then, from the Mac:
   `POST /api/apple-host/enroll {"name": "mac-enzo", "code": "penr_..."}`. The answer holds the `pmac_...` token, shown once.
4. Save the token: `sudo install -m 600 -o palabre /dev/null /etc/palabre-apple-worker.token`, then paste it in that file.
5. Pull the image as the worker user: `sudo -u palabre tart pull <image@sha256:...>` (the digest set as `APPLE_IMAGE` on the server).
6. Write `/etc/palabre-apple-worker.toml` (no secret in it):

   ```toml
   backend_url = "https://palabre.example.com"
   token_file = "/etc/palabre-apple-worker.token"
   image = "ghcr.io/example/macos-xcode@sha256:<64 hex>"
   max_vms = 2
   job_timeout_seconds = 1800
   # Optional, added after the isolation arguments the worker always applies (see below):
   # net_extra_args = ["--net-softnet-allow=203.0.113.10/32"]
   ```

   The worker always starts VMs with `--net-softnet` and blocks `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` and
   `169.254.0.0/16`, so the VM (which runs untrusted code) reaches neither the Mac nor your LAN. It cannot be turned off
   from the config. If the server lives on a private address, allow exactly that host with `net_extra_args`
   (`--net-softnet-allow=<ip>/32`). `backend_url` must use `https://`. `job_timeout_seconds` starts after `tart clone` and the
   VM start, and includes the boot probe.

   DNS: the VM needs a resolver. If name resolution fails because the private ranges are blocked, allow only the softnet
   gateway with `net_extra_args = ["--net-softnet-allow=192.168.64.1/32"]`, not the whole `192.168.0.0/16`.

7. From a copy of the repository, run `cd deploy/apple-host && sudo ./install.sh`. It copies the worker to
   `/usr/local/lib/palabre-apple-worker`, installs the launchd daemon (starts at boot, restarted on failure) and starts it.

   The same script installs the second network barrier, a `pf` anchor, see the next section. The worker refuses to start
   (clear message in the log) while that anchor is not loaded.

Check: `tail -f /var/log/palabre-apple-worker.log`, and the Mac shows as connected in the app.
Upgrade the worker: pull the repository and run `sudo ./install.sh` again (it is idempotent).

## Second network barrier: the `pf` anchor

Tart's softnet is the first barrier; the anchor is the second, on the host. `install.sh` fills
`com.palabre.apple-vm.pf.conf` and loads it as the anchor `palabre/apple-vm`. From the VM subnet (`192.168.64.0/24`, Tart's
default, change it with `VM_NET=... VM_GATEWAY=... VM_IF=... sudo -E ./install.sh`) it blocks `10.0.0.0/8`, `172.16.0.0/12`,
`192.168.0.0/16`, `169.254.0.0/16` and every IP address the Mac has, with one exception: DNS (port 53) to the gateway only.
All IPv6 traffic coming in from the VM bridge (`bridge100` by default, `VM_IF`) is dropped too, so a guest cannot reach the Mac by its `fe80::` address. Internet stays open over IPv4. It is idempotent: it adds one `anchor` line to `/etc/pf.conf` (copy kept in `/etc/pf.conf.palabre-backup`), installs the
`com.palabre.apple-pf` daemon that enables `pf` at boot, and a sudoers entry that lets `palabre` run only
`pfctl -a palabre/apple-vm -s rules`, which is how the worker proves the anchor is loaded before it starts. Run `install.sh`
again after the Mac's IP changes or after a macOS update that resets `/etc/pf.conf`.

A backend on a private address is blocked by the anchor too: use a public address (or a tunnel).

### Commissioning check (required before the first real job)

Inside a VM (`tart run` a clone of the image, then `tart exec`), copy `check-isolation.sh` and run it with the Mac's LAN IP
(and other LAN hosts, such as the router):

```sh
tart exec <vm> /bin/sh -s -- <mac_ip> <router_ip> < deploy/apple-host/check-isolation.sh
```

It also probes the VM's default gateway and the link-local IPv6 neighbours of the VM's link, which must not answer. It fails if the Mac, a LAN address, one address of each private range or `169.254.169.254` accepts or refuses a connection
(only a dropped packet counts as blocked), or if `github.com` or `swiftpackageindex.com` is not reachable. Run it again after
every change of network, of image or of `pf`. With softnet on, the check also passes if softnet alone works, so it does not
prove the anchor by itself: run it once more in a VM started without the softnet flags (plain `tart run`, no
`--net-softnet`), where it must also pass; that proves the second barrier alone. The worker checks that pf is enabled and the
anchor is loaded only at startup, so restart it after any `pfctl -d` or macOS update. Not run on the real Mac yet: the rules are checked by `pfctl -n` only
at install time, so this step is the real proof.

## Tests

`cd deploy/apple-host && python3 -m unittest test_worker` : the queue limit, timeouts, cleanup, verdicts and the refusal to start without the anchor, with a
fake VM tool and a fake backend (no Mac needed).

## Known limit: no GUI session (LaunchDaemon vs LaunchAgent)

The installer sets up a LaunchDaemon. Virtualization.framework may refuse to boot macOS guests without a logged-in GUI session, and a LaunchDaemon has none.
Not validated on the real Mac yet. If `tart run` fails from the daemon, use a LaunchAgent instead: put the plist in
`/Users/palabre/Library/LaunchAgents/`, enable automatic login for `palabre`, and load it with
`launchctl bootstrap gui/<uid> <plist>`. Roll back the same way with `launchctl bootout gui/<uid> <plist>`.

## Roll back

- Stop the worker: `sudo launchctl bootout system /Library/LaunchDaemons/com.palabre.apple-worker.plist`, and remove that file
  and `/usr/local/lib/palabre-apple-worker` to uninstall. Leftover VMs: `tart list`, then `tart delete job-<id>`.
- Revoke the token: `DELETE /api/apple-hosts/{id}`.
- Network barrier: `sudo launchctl bootout system /Library/LaunchDaemons/com.palabre.apple-pf.plist`, remove that file,
  `/etc/pf.anchors/palabre-apple-vm` and `/etc/sudoers.d/palabre-apple-pf`, restore `/etc/pf.conf.palabre-backup`
  to `/etc/pf.conf`, then `sudo pfctl -f /etc/pf.conf`. The worker will not start without the anchor: do this only with
  the worker stopped (softnet still isolates the VMs).
- Previous image: put the previous digest in the config file (and in `APPLE_IMAGE`), then `sudo ./install.sh`.
