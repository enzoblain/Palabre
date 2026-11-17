# macOS build image

The image each Apple build VM starts from, and the script that builds in it. The worker that clones the image per job is in
[Mac builder](apple-host.md); the structure and security rules are in [Apple mode](apple-mode.md). Code: `deploy/apple-image/`.

## What is in it

- `macos.pkr.hcl`: Packer template (Tart plugin, pinned `1.14.0`). It starts from a pinned base image (`base_image`, `name@sha256:...`, enforced by a validation block that refuses anything without a 64-hex digest,
  an Apple-silicon macOS image with Xcode and an `admin` user with passwordless sudo, for example a Cirrus Labs one) and runs `provision.sh`.
- `provision.sh`: creates the unprivileged `builder` user, installs SwiftLint and xcbeautify, installs the runner, wipes shell
  history and git credentials, then gives `admin` a random password nobody keeps. No secret is ever put in the image.
- `palabre-job-runner.sh`: installed as `/usr/local/bin/palabre-job-runner`. The worker runs it in each fresh VM with
  `tart exec`: `palabre-job-runner <backend_url> <job_id> <source_url> <commit_sha>`, with the one-time job token on the standard input.

## Build the image

On the Mac (Apple silicon), with Tart installed (see [Mac builder](apple-host.md)):

```sh
brew install cirruslabs/cli/packer
cd deploy/apple-image
packer init .
packer build -var base_image=<base-image@sha256:...> .
```

Expected: a local Tart VM named `palabre-macos` (`tart list`). Test it by hand: `tart run palabre-macos`, then
`tart exec palabre-macos palabre-job-runner` must print a usage line and exit `20`.
Publish it where the Macs pull it (`tart push palabre-macos <registry>/<name>:<tag>`), then set the resulting digest as
`APPLE_IMAGE` on the server and as `image` in each worker config. The worker never pulls a tag, only a digest.

## What the runner does

1. Reads the job token from the standard input, refuses it if it holds anything outside `[A-Za-z0-9_-]` (it is written into a curl
   config), and downloads the source bundle with curl (HTTPS only, 300 s limit). The token goes
   to curl through its standard input, never in an argument, so it does not show in a process list. The bundle is served once per
   token, so there is no retry.
2. Clones the bundle and checks out the commit, in `/private/tmp/palabre-work/job-<id>`, owned by `builder`.
3. Runs `swift build` then `swift test` as `builder`, with an empty environment: build code (plugins, scripts) never sees the token.
4. Removes its work folder, whatever the result.

Exit code: `0` passed, `10` build or tests broken, `20` for any infra problem (download or clone failed, bad arguments, no token).
The worker turns `10` into a failed job and every other code into `error`, which can be retried, not a red build.

Fresh VM, time limit and deletion are done by the worker, not by the runner: a stuck job is stopped at `job_timeout_seconds` and
reported as `error`, the VM is deleted on success and on failure, and a VM that does not start or a failed clone is an `error` too.

## Admin and builder boundary

- `builder` runs the untrusted build code with an empty environment. It has no sudo and cannot read the admin home.
- `admin` runs the runner (token, download, cleanup) and keeps passwordless sudo, which `tart exec` and the runner need.
- At the end of provisioning `admin` gets a random password that is not stored, so the well-known `admin/admin` of the base image
  does not stay in the final image (build code cannot `su` to admin with it). Building the image still works: Packer's SSH session
  is already open, and a later build starts again from the pinned base image with `admin/admin`. Passwordless sudo is kept on
  purpose, so this is defense in depth, not a barrier against code already running as admin.

## Tests

`cd deploy/apple-image && python3 -m unittest test_runner`: exit codes, token kept out of the arguments, refusal of bad input (arguments, a source url that is not a path, a token with unexpected characters),
with fake `curl`, `git` and `swift` (no Mac needed). The Packer template has not been run on a real Mac yet.

## Roll back

Point `APPLE_IMAGE` and the workers' `image` back to the previous digest, then `sudo ./install.sh` on the Mac. Delete a bad local
image with `tart delete palabre-macos`.
