# End-to-end trial of the Swift build on the real Mac

Proof that an Apple pull request triggers a build in a fresh VM on the real Mac, gates the merge, and reports errors on the task.
Prerequisites: the Mac is "Connected" in "Build Mac" ([Mac builder](apple-host.md)), the isolation check passed, the image is built
([macOS image](apple-image.md)). Run it with the Mac owner; the Linux side cannot do it.

## Steps and expected results

1. Create a small Apple task on a project in Apple mode. Add a Swift package with one test that passes.
   - Open the PR: a build appears queued on the task without any action (web and mobile).
2. Watch the Mac: `tart list` shows a fresh VM for the job, deleted at the end (`tart list` empty again).
3. Break a test on purpose (an `XCTAssertEqual` that fails) and push.
   - The build ends **red** and the compiler/test error shows on the task, in web and in mobile.
   - Merge is blocked while red.
4. Fix the test and push.
   - The build turns green, merge is unblocked.
5. Infra error: queue a build, then stop the worker mid-job (`sudo launchctl bootout system/<worker label>`).
   - After the heartbeat timeout the job is classed **infra error**, not red build.
   - Restart the worker, press the retry button on the task: the build runs again.

## Report to attach to the task

Fill one line per step: result, screenshot or log excerpt (`/var/log/palabre-apple-worker.log`, web and mobile screenshots). Never paste
tokens or enrollment codes.

## Roll back

Nothing to undo: the trial only creates a test task and PR. Close the PR and delete the test project; `tart delete` any leftover VM.
