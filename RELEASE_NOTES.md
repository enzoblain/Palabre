# Palabre v0.2.0

## Highlights

- **`dev` by default**: every new project works on a `dev` branch. Task PRs target `dev`, and a release PR from `dev` to `main` ships the work.
- **Channels**: conversations are organized in channels in the front.
- **Interactive messages**: messages can carry Validate / Reject / Nuance buttons, so the CEO answers a decision or proposal in one click.
- **Inbox removed**: the inbox is gone; what it showed now lives in channels and interactive messages.
- **Usage in settings**: the settings page shows the Claude account usage.

## Also in this release

- The lead can merge releases, tag and publish versions. The merge is pinned to the checked commit and requires green CI before tagging.
- Task branches are cleaned up automatically after merge.

## Version

Bumped to 0.2.0 in `package.json`, `package-lock.json`, `tauri.conf.json`, `Cargo.toml` and `Cargo.lock`.
