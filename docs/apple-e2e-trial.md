# End-to-end trial of the Swift build on the real Mac

Proof that an Apple pull request triggers a build in a fresh VM on the real Mac, gates the merge, reports errors on the task, and that the
image's default admin password was changed. Only the Mac owner can run it; the Linux side cannot. No development knowledge is needed: copy
the commands as they are.

Prerequisites:

- the Mac shows **Connected** in "Build Mac" ([Mac builder](apple-host.md));
- the isolation check passed and the image is built and published ([macOS image](apple-image.md));
- an Apple project exists (created with "Swift / iPhone app") and the lead has given you one small Apple task on it, with its pull request
  branch. Ask the lead if you have none.

A build is not queued by a plain `git push` or by opening the pull request on GitHub: it is queued each time the lead **submits the
task** (a new submission of the pull request). So after every push below, ask the lead: "please submit task <number> again", then check
the build. Always send back the commit you pushed (`git rev-parse --short HEAD`) so the build can be matched to it.

Each step has three parts: what to do, what to observe, what to send back. Send everything in one report at the end (see "Report"). Never
send tokens, enrollment codes or any password, only the words "ok" or "refused".

Terminal commands run on the Mac, in Terminal, as the administrator, unless said otherwise.

## Step 1: a first build starts by itself

What to do:

1. On the Mac, get the project and the task branch (the lead gives the repository address and the branch name):
   ```sh
   git clone <repository address> trial && cd trial && git checkout <task branch>
   ```
2. Create a tiny Swift package with one passing test:
   ```sh
   mkdir -p Sources/Trial Tests/TrialTests
   cat > Package.swift <<'EOF'
   // swift-tools-version:5.9
   import PackageDescription
   let package = Package(
       name: "Trial",
       targets: [
           .target(name: "Trial"),
           .testTarget(name: "TrialTests", dependencies: ["Trial"]),
       ]
   )
   EOF
   echo 'public func add(_ a: Int, _ b: Int) -> Int { a + b }' > Sources/Trial/Trial.swift
   cat > Tests/TrialTests/TrialTests.swift <<'EOF'
   import XCTest
   @testable import Trial
   final class TrialTests: XCTestCase {
       func testAdd() { XCTAssertEqual(add(2, 3), 5) }
   }
   EOF
   git add -A && git commit -m "test: add trial package" && git push
   ```
   If the project has no `.palabre/apple.toml` yet, ask the lead for its content and add it in the same commit, before the first
   submission: the build reads it from the task branch.
3. Ask the lead to submit the task (opening the pull request on GitHub is not enough). Send them the commit (`git rev-parse --short HEAD`).

What to observe, without pressing anything else:

- On the task page in the web app, and in the mobile app, a build appears as **queued**, then **running**, then **passed** (green).
- While it is **running**, in a second Terminal window run `sudo -u palabre tart list`. You must see one VM named `job-<number>`. The VM
  only lives during the build, so run the command as soon as the build shows "running". After the build, run it again: the `job-<number>`
  VM must be gone.

What to send back: a screenshot of the task page (web) and of the mobile app showing the build, the output of `tart list` during the
build and after it, and the last 50 lines of the worker log: `tail -n 50 /var/log/palabre-apple-worker.log`.

## Step 2: break a test on purpose, the build turns red and the merge is blocked

What to do: break the test, then push:
```sh
sed -i '' 's/XCTAssertEqual(add(2, 3), 5)/XCTAssertEqual(add(2, 3), 6)/' Tests/TrialTests/TrialTests.swift
git commit -am "test: break the trial test on purpose" && git push
```

What to observe:

- After the lead submits the task again, a new build is queued for the new commit and ends **failed** (red).
- The task page, in the web app and in the mobile app, shows the error: the failed test name `testAdd` and a message like
  `XCTAssertEqual failed: ("5") is not equal to ("6")`.
- The merge is blocked. The task page has no merge button: the merge is done by the lead (or by you through the lead). Ask the lead to
  try to merge the task and to copy you the blocker text. It must say the Apple build failed (fix and submit again).

What to send back: screenshots of the red build with its error on web and on mobile, the commit you pushed, and the blocker text the
lead copied.

## Step 3: fix the test, the build turns green and the merge is unblocked

What to do: fix the test, push, then ask the lead to submit the task again:
```sh
sed -i '' 's/XCTAssertEqual(add(2, 3), 6)/XCTAssertEqual(add(2, 3), 5)/' Tests/TrialTests/TrialTests.swift
git commit -am "test: fix the trial test" && git push
```

What to observe: a new build runs and ends **passed** (green). Ask the lead to try the merge again (the lead must not go through with it,
or must cancel): the Apple build must no longer be listed as a blocker. The old red build stays in the history.

What to send back: a screenshot of the green build, the commit, and the lead's new merge answer.

## Step 4: an infra error (worker stopped), then retry

What to do:

1. Push an empty commit, then ask the lead to submit the task again to queue a new build:
   `git commit --allow-empty -m "test: infra trial" && git push`.
2. As soon as the build shows **running**, stop the worker:
   ```sh
   sudo launchctl bootout system /Library/LaunchDaemons/com.palabre.apple-worker.plist
   ```
3. Wait about 2 minutes. The server declares the Mac lost after 60 seconds of silence (`APPLE_HEARTBEAT_TIMEOUT_SECONDS`, default `60`).
   Overdue builds are only noticed when something asks for work, so the build may stay **running** for a while. If it is still
   **running** after 5 minutes, ask the lead to check; do not restart the worker yet.

What to observe:

- In "Build Mac", the Mac turns **Disconnected**.
- The build ends as **Erreur d'infrastructure** (a warning, clearly not a red build: no test failure is shown). On the task page a
  **Relancer** button appears next to it.
- Put the worker back first (next command), wait until "Build Mac" shows **Connected** again, then press **Relancer** on the task page
  (it only works on the newest build, when it ended as an infrastructure error).
  The build is queued again for the same commit and ends **passed**.

Put the worker back in service:
```sh
sudo launchctl bootstrap system /Library/LaunchDaemons/com.palabre.apple-worker.plist
tail -n 20 /var/log/palabre-apple-worker.log
```
Expected: the log shows the worker starting without an error, and the Mac is **Connected** again in "Build Mac" within a few seconds. If
`tart list` shows a leftover `job-<number>` VM from the stopped build, run `sudo -u palabre tart delete job-<number>`.

What to send back: screenshots of "Erreur d'infrastructure" (with the **Relancer** button), of the green build after the retry, of "Build Mac" showing
Connected, and the output of the `tail` command.

## Step 5: the image's admin password was changed

The base image ships an `admin` account with the well-known password `admin`. The hardening of the image changes it. Check on a VM cloned
from the published image that the old password no longer works and the new one does.

What to do:

1. Start a throw-away VM from the image (use the exact `APPLE_IMAGE` name the server admin gave you; see [Mac builder](apple-host.md), step
   6). In a first Terminal window:
   ```sh
   sudo -u palabre tart clone <image@sha256:...> check-admin
   sudo -u palabre tart run --no-graphics check-admin
   ```
   In a second window, get its address: `sudo -u palabre tart ip check-admin` (a number like `192.168.64.x`).
2. Try the old password. Run `ssh admin@<address>` and type `admin` when asked.
   Expected: **refused** (`Permission denied`). If you get a prompt on the VM, stop here and tell the lead at once.
3. Try the new password: run `ssh admin@<address>` again and type the new password. The server admin gives it to you through a private
   channel, not through the chat or the report. Expected: you are logged in. Type `exit`.
4. Clean up: in the first window press Control-C, then `sudo -u palabre tart delete check-admin`.

What to send back: only "old password refused: yes/no" and "new password accepted: yes/no", plus a screenshot of the `Permission denied`
message. Never the password itself.

## Report

Send the lead one message (or attach it to the task) with one line per step: ok or not ok, and the items listed under "What to send back".
Sacha checks the report. Make sure no screenshot or log shows a token (`penr_`, `pmac_`) or a password.

## Clean up and roll back

- The worker must be running again (end of step 4). Check: "Build Mac" shows **Connected**.
- Close the trial pull request and delete its branch on GitHub, and ask the lead to cancel the trial task.
- Delete the local copy: `cd .. && rm -rf trial`.
- No VM must remain: `sudo -u palabre tart list` shows only the image. Delete leftovers with `sudo -u palabre tart delete <name>`.
- Nothing else was changed on the Mac or the server, so there is nothing more to undo.
