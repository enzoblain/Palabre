# TestFlight for a Swift project

How a Swift project ([Apple mode](apple-mode.md)) is signed and sent to TestFlight. Signing and upload run
only in GitHub Actions, on a macOS runner, in a protected environment. The Mac builder, the VMs and the agents never
see an Apple key. The App Store submission stays manual.

## What happens

1. In the web app, the "Publish to TestFlight" button on the info page of a Swift project (it shows the version sent or the translated error) starts the publication for the latest release: `POST /api/projects/{id}/testflight` (admin
   token, Apple mode on). Palabre takes the latest `vX.Y.Z` tag, refuses if the checks of its commit are red or still running
   (`apple_publish_build_not_green`), then starts the workflow `swift-testflight.yml` on that tag. The answer is `202` with the version.
2. The workflow has four jobs. `verify` (no secret) checks the run is on the tag `vX.Y.Z` of the version asked. `test` (no secret)
   runs `xcodebuild test`. `archive` (no secret) builds an unsigned archive with the version of the release as
   marketing version (`MARKETING_VERSION`) and the run number as build number, and passes it on as a one-day artifact.
   `testflight` needs `archive`: it is the only job with the environment `testflight`, so
   a red build or test ends the run before any key is read.
3. `testflight` does not check out the repository: no project code (build phases, package scripts) runs next to the keys.
   It downloads the archive, imports the certificate (usable by `codesign` only) and the profile into a temporary keychain,
   signs and exports the IPA with `xcodebuild -exportArchive`, and uploads it with the App Store Connect key.
   If the export does not sign an unsigned archive correctly for a given project, re-sign the `.app` with `codesign` in this same job, still without a checkout.
   The keychain and the decoded keys are deleted in a last step, even on failure.

Errors are annotations in French on the run (certificate expired or unreadable, profile expired, key or account refused,
build already at Apple, red tests). Palabre's own refusals are the `apple_publish_*` error codes, translated in the apps.

## Setup (once, for Enzo)

The Apple side (app in App Store Connect, API key, distribution certificate, App Store profile) is the same as for the
mobile app: follow steps 1 to 3 of [Mobile release](mobile-release.md#guide-for-enzo), with the bundle identifier of the Swift app.

In the Swift project's GitHub repository:

1. Copy `deploy/apple-templates/swift-testflight.yml` of Palabre to `.github/workflows/swift-testflight.yml`. (Palabre does not
   push it itself: pushing a workflow file needs the `workflow` scope on the GitHub token.)
2. Settings > Secrets and variables > Actions > Variables: add `APPLE_SCHEME`, the name of the Xcode scheme of the app
   (the project needs an app target: a Swift package with only a library cannot be archived).
3. Settings > Environments > New environment `testflight`: **Deployment branches and tags** > Selected > tag rule `v*`;
   **Required reviewers**: you.
4. In that environment, add the **environment secrets** (never repository secrets), files as base64:

| Secret | Value |
| --- | --- |
| `ASC_KEY_ID` | Key ID of the API key |
| `ASC_ISSUER_ID` | Issuer ID |
| `ASC_KEY_P8_BASE64` | the `.p8` file |
| `IOS_DIST_CERT_P12_BASE64` | the `.p12` file |
| `IOS_DIST_CERT_PASSWORD` | password of the `.p12` |
| `IOS_PROVISIONING_PROFILE_BASE64` | the `.mobileprovision` file |

If the start answers `apple_publish_workflow_missing`, the file of step 1 is missing or is not on the tag (publish a new
version after adding it: the workflow is read from the tag).

## Run by hand

Actions > Swift TestFlight > Run workflow, pick the **tag** `vX.Y.Z` and type `X.Y.Z`. Approve the environment.

## Rollback and rotation

- A bad build: expire it in App Store Connect > TestFlight. Nothing is published automatically.
- Stop the pipeline: disable the workflow in Actions or delete the `testflight` environment.
- Leaked or lost secret: revoke the key or certificate at Apple, create a new one, replace the secret.
- Revert this feature: remove the workflow file from the project; the endpoint then answers `apple_publish_workflow_missing`.
