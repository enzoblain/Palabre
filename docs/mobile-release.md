# Mobile release: TestFlight and Android build

How the mobile app ([Mobile app](mobile.md)) is built and sent out. The workflow is
`.github/workflows/mobile-release.yml`. Nothing here uses EAS or another paid service: the builds run on
GitHub-hosted runners and the signing material stays in our own GitHub secrets.

## What happens

On every `vX.Y.Z` tag (so on every published version), or on a manual run of the workflow:

- **iOS** (macOS runner): the app is built, signed, and uploaded to **TestFlight**. The marketing version is the
  release version, the build number is the run number. The App Store submission stays manual: in App Store
  Connect, pick the TestFlight build and submit it.
- **Android** (Linux runner): an `.aab` bundle signed with the upload key is attached to the run as an artifact
  (kept 30 days). It is **not** published to the Play Store yet.

Both jobs skip themselves if `mobile/` is missing. The pull request CI (`ci.yml`, job "Mobile check") only
runs `npm run check` in `mobile/` (type check, lint, tests) on Linux: no macOS runner, no secret.

## Guide for Enzo

Prerequisite: a paid Apple Developer account. You do these steps once; the team never sees the values.

### 1. Create the app in App Store Connect

1. Choose the app identifier, in reverse-domain form (for example `com.yourname.palabre`), and tell the lead:
   the team sets it in `mobile/app.json` as `expo.ios.bundleIdentifier` and `expo.android.package`. Until it
   is set, the workflow stops at its first job with a clear message. It cannot be changed once the app is published.
2. App Store Connect > Apps > "+" > New App, with that bundle identifier.

### 2. Create the App Store Connect API key

1. App Store Connect > Users and Access > Integrations > App Store Connect API > "+".
2. Name it `palabre-ci`, access **Developer** first. If the TestFlight upload is refused for lack of rights, recreate the key with **App Manager**.
3. Download the `.p8` file (Apple gives it only once). Note the **Key ID** and the **Issuer ID** shown on the page.

### 3. Create the distribution certificate and the profile

1. Developer portal > Certificates > "+" > **Apple Distribution**. Follow the steps (a certificate request made
   with Keychain Access on your Mac), then download the `.cer` and install it.
2. In Keychain Access, export the certificate with its private key as a `.p12`, with a strong password.
3. Developer portal > Profiles > "+" > **App Store Connect** (distribution). Pick the app and the certificate,
   download the `.mobileprovision`.

### 4. Create the Android upload key

```sh
keytool -genkeypair -v -keystore upload.keystore -alias upload -keyalg RSA -keysize 2048 -validity 10000
```

Keep the file and its passwords in your password manager: losing the key means asking Google for a reset.

### 5. Put the secrets in GitHub

1. Repository > Settings > Environments > New environment, named `mobile-release`.
2. In it: **Deployment branches and tags** > Selected > add the tag rule `v*`; **Required reviewers**: you.
3. Add these as **environment secrets** (not repository secrets). For files, give the base64 text:
   `base64 -i file | pbcopy` on macOS, then paste.

| Secret | Value |
| --- | --- |
| `ASC_KEY_ID` | Key ID of the API key |
| `ASC_ISSUER_ID` | Issuer ID |
| `ASC_KEY_P8_BASE64` | the `.p8` file, base64 |
| `IOS_DIST_CERT_P12_BASE64` | the `.p12` file, base64 |
| `IOS_DIST_CERT_PASSWORD` | password of the `.p12` |
| `IOS_PROVISIONING_PROFILE_BASE64` | the `.mobileprovision` file, base64 |
| `ANDROID_KEYSTORE_BASE64` | `upload.keystore`, base64 |
| `ANDROID_KEYSTORE_PASSWORD` | keystore password |
| `ANDROID_KEY_ALIAS` | `upload` |
| `ANDROID_KEY_PASSWORD` | key password |

### 6. Check

The iOS and Android jobs each use the environment, so you approve **twice** per release (once per job).

Run the workflow by hand (Actions > Mobile release > Run workflow). In "Use workflow from", pick an existing
`vX.Y.Z` **tag**, not a branch: the environment refuses anything else, and the run fails with a clear message.
Approve the environment, and look for the build in App Store Connect > TestFlight (Apple processes it for a few minutes).

## Security rules the workflow follows

- Triggered only by a version tag or by hand, never by a pull request, so no fork code reaches a secret.
- The secrets are in the `mobile-release` environment (tags `v*`, required reviewers), passed to the one step
  that needs them as environment variables, never written in a command line or echoed.
- The certificate goes into a temporary keychain with a random password, deleted in a final step that runs even
  when the build fails. Decoded keys and profiles are deleted there too.
- Third-party actions are pinned by commit SHA, Xcode and Node are pinned, `permissions` is `contents: read`.

## Rotation and rollback

- A leaked or lost secret: revoke the API key in App Store Connect (or the certificate in the developer portal),
  create a new one, replace the secret in the environment.
- A bad build: in App Store Connect, expire the TestFlight build. Nothing is published automatically, so there
  is nothing else to undo. Fix, then publish a new version.
- To stop the pipeline: disable the "Mobile release" workflow in Actions, or delete the environment.
- To revert this change: remove `mobile-release.yml` and the "Mobile check" job of `ci.yml`.
