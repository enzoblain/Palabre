# TestFlight for a Swift project

How a Swift project ([Apple mode](apple-mode.md)) is signed and sent to TestFlight. Signing and upload run
only in GitHub Actions, on a macOS runner, in a protected environment. The Mac builder, the VMs and the agents never
see an Apple key. The App Store submission stays manual.

## What happens

1. In the web app, the "Publish to TestFlight" button on the info page of a Swift project (it asks for a confirmation, then shows the version sent or the translated error) starts the publication for the latest release: `POST /api/projects/{id}/testflight` (admin
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

Everything below is done by you, once, on your own Apple and GitHub accounts. The values never go in the repository, in a
VM, on an agent's machine or in a chat: they go only in the protected GitHub environment `testflight` (step 5).

### 1. Apple Developer account

1. Sign in at developer.apple.com with your Apple ID (two-factor authentication on).
2. Enroll in the Apple Developer Program (paid, yearly). Approval can take a day or two. Without it, nothing below works.
3. Renew it every year: an expired membership makes certificates and keys stop working.

### 2. Create the app in App Store Connect

1. Developer portal > Certificates, Identifiers & Profiles > Identifiers > "+" > App IDs > App: give the **bundle
   identifier** of the Swift app (the one in the Xcode project) and keep it: it cannot change once published.
2. App Store Connect > Apps > "+" > New App, with that same bundle identifier.

### 3. Create the App Store Connect API key

1. App Store Connect > Users and Access > Integrations > App Store Connect API > "+".
2. Name it `palabre-ci`, access **Developer**. If the upload is refused for lack of rights, recreate it with **App Manager**.
3. Download the `.p8` file (Apple gives it only once). Note the **Key ID** and the **Issuer ID** shown on the page.

### 4. Create the distribution certificate and the profile

1. On your Mac, Keychain Access > Certificate Assistant > Request a Certificate From a Certificate Authority: save the
   request (`.certSigningRequest`) to disk.
2. Developer portal > Certificates > "+" > **Apple Distribution**: upload the request, download the `.cer`, double-click
   it to install it.
3. In Keychain Access, export that certificate with its private key as a `.p12`, with a strong password.
4. Developer portal > Profiles > "+" > **App Store Connect** (distribution): pick the app of step 2 and the certificate of
   step 2, then download the `.mobileprovision`.

### 5. Put everything in GitHub

In the Swift project's GitHub repository:

1. Copy `deploy/apple-templates/swift-testflight.yml` of Palabre to `.github/workflows/swift-testflight.yml`. (Palabre does not
   push it itself: pushing a workflow file needs the `workflow` scope on the GitHub token.)
2. Settings > Secrets and variables > Actions > Variables: add `APPLE_SCHEME`, the name of the Xcode scheme of the app
   (the project needs an app target: a Swift package with only a library cannot be archived).
3. Settings > Environments > New environment `testflight`: **Deployment branches and tags** > Selected > tag rule `v*`;
   **Required reviewers**: you.
4. In that environment, add the **environment secrets** (never repository secrets). For a file, paste its base64 text:
   `base64 -i file | pbcopy` on macOS.

| Secret | Value | Where it comes from |
| --- | --- | --- |
| `ASC_KEY_ID` | Key ID of the API key | step 3, page of the key |
| `ASC_ISSUER_ID` | Issuer ID | step 3, top of the same page |
| `ASC_KEY_P8_BASE64` | the `.p8` file, base64 | step 3, downloaded once |
| `IOS_DIST_CERT_P12_BASE64` | the `.p12` file, base64 | step 4, export from Keychain Access |
| `IOS_DIST_CERT_PASSWORD` | password of the `.p12` | the one you chose when exporting |
| `IOS_PROVISIONING_PROFILE_BASE64` | the `.mobileprovision` file, base64 | step 4, developer portal |

5. Delete the downloaded `.p8`, `.p12` and `.mobileprovision` files and the clipboard content once pasted; keep a copy
   only in your own password manager.

If the start answers `apple_publish_workflow_missing`, the file of step 1 is missing or is not on the tag (publish a new
version after adding it: the workflow is read from the tag).

## Check that it works

1. Publish a release (or run by hand, see below) and approve the environment when GitHub asks.
2. The four jobs `verify`, `test`, `archive`, `testflight` are green.
3. In App Store Connect > the app > TestFlight, the build appears after a few minutes of Apple processing.

## Common errors

The workflow prints these as annotations in French on the run.

| Message (translated) | Cause and fix |
| --- | --- |
| Apple secret missing in the environment | A secret of the table is absent, misspelled, or set as a repository secret instead of an environment secret. |
| Certificate unreadable: wrong password or damaged file | `IOS_DIST_CERT_PASSWORD` does not match the `.p12`, or the base64 was cut. Re-export and re-paste. |
| Provisioning profile expired | Profiles last one year. Create a new one (step 4.4) and replace the secret. |
| Signing failed: certificate, profile or app identifier do not match | The profile was made for another app or certificate. Recreate it with the right ones. |
| Apple refuses the upload: certificate or profile expired or revoked | The distribution certificate lasts one year or was revoked. Redo step 4 and replace the three secrets. |
| Apple refuses the App Store Connect key | Wrong Key ID or Issuer ID, key revoked, wrong role (use App Manager), or membership expired. |
| This version is already at Apple | Run the publication again: the build number is the run number, so it changes. |
| `APPLE_SCHEME` variable missing | Add the repository variable of step 5.2. |

## Run by hand

Actions > Swift TestFlight > Run workflow, pick the **tag** `vX.Y.Z` and type `X.Y.Z`. Approve the environment.

## Rollback and rotation

- A bad build: expire it in App Store Connect > TestFlight. Nothing is published automatically.
- Stop the pipeline: disable the workflow in Actions or delete the `testflight` environment.
- Leaked or lost secret: revoke the key or certificate at Apple, create a new one, replace the secret.
- Revert this feature: remove the workflow file from the project; the endpoint then answers `apple_publish_workflow_missing`.
