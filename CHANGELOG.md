# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.4] - 2026-10-28

### Added

- The lead is woken up when the CI of the release PR and of `main` (production) ends, with the result, so a failed release CI no longer goes unnoticed.
- The `release_ci_sha`, `main_ci_sha` and `main_ci_watch` project columns (nullable, or default false), added automatically at startup. Nothing to do when upgrading from 0.2.3.

### Fixed

- Tests: the usage cache locks are cleared between tests.

## [0.2.3] - 2026-10-28

### Added

- Real Claude usage per model: the settings Usage screen works like `/usage`, per account and per model, read from Claude's OAuth usage endpoint and cached for about a minute.
- The lead is woken up when a task can be merged, and reminded once if it waits too long. The orchestrator also announces its steps in the chat.
- The `merge_ready_at` and `lead_reminded_at` task columns and the `messages.is_system` column (NOT NULL, default false, so existing messages stay normal), added automatically at startup. Nothing to do when upgrading from 0.2.2.

### Changed

- System lines from "Palabre" no longer look like the boss's messages: they show as muted platform announcements.

### Fixed

- Usage tracking hardening: httpx/httpcore logs lowered to WARNING so request headers never reach the logs, and a lock on the usage cache.

## [0.2.2] - 2026-10-28

### Changed

- Unread badges in direction only: team channels no longer show a new-message count (the live dot stays), and the app stops polling them for it.

## [0.2.1] - 2026-10-28

### Added

- Outside pull requests: the lead triages the PRs no task owns, such as Dependabot's. `list_pull_requests` shows every open PR with its task, and `close_pull_request` closes one with a comment and deletes its branch. A task's PR, the release PR, production, the team's branch and forks' branches are left alone. Nothing to do when upgrading from 0.2.0: the lead gets the two tools on restart.

## [0.2.0] - 2026-10-28

### Added

- Channels: team channels are read-only for the CEO, who follows them live, and the lead can open new ones (`create_channel`).
- Interactive messages: the lead's messages can carry Validate / Reject / Nuance buttons, so the CEO answers a decision or proposal in one click.
- Usage in settings: the settings page shows the Claude account usage.
- The lead can merge releases, tag and publish versions. The merge is pinned to the checked commit and requires green CI before tagging.
- Task branches are cleaned up automatically after a merge or a cancellation. `POST /api/tasks/cleanup` cleans up the existing leftovers.

### Changed

- `dev` by default: every new project works on a `dev` branch. Task PRs target `dev`, and a release PR from `dev` to `main` ships the work. Existing projects stay on their current branch; use the settings or `set_working_branch` to switch.
- The CEO only talks to the lead, in `#direction`. A direction channel is created at startup for every existing project.
- Escalations show up where they were written.

### Removed

- Inbox: what used to wait in it is now a request in `#direction`, converted on the first startup.
- The `/notifications` API: clients that use it will break.

## [0.1.10] - 2026-10-28

## [0.1.9] - 2026-10-28

## [0.1.8] - 2026-10-28

## [0.1.7] - 2026-10-28

## [0.1.6] - 2026-10-28

### Fixed

- The server failing to start.

## [0.1.5] - 2026-10-28

## [0.1.4] - 2026-10-28

## [0.1.3] - 2026-10-28

## [0.1.2] - 2026-10-28

### Added

- New `web` service: nginx serves the interface on port 2810 (`PALABRE_WEB_PORT`) and passes `/api` on to the backend, so a phone only needs one address.
- Small screens: a top bar with a menu button, the sidebar slides over the page.
- The release workflow also publishes `ghcr.io/enzoblain/palabre-web`.

### Changed

- In a browser, the connect screen asks for the token only.

## [0.1.1] - 2026-10-28

## [0.1.0] - 2026-10-28

Initial release.

[Unreleased]: https://github.com/enzoblain/Palabre/compare/v0.2.4...HEAD
[0.2.4]: https://github.com/enzoblain/Palabre/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/enzoblain/Palabre/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/enzoblain/Palabre/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/enzoblain/Palabre/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/enzoblain/Palabre/compare/v0.1.10...v0.2.0
[0.1.10]: https://github.com/enzoblain/Palabre/compare/v0.1.9...v0.1.10
[0.1.9]: https://github.com/enzoblain/Palabre/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/enzoblain/Palabre/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/enzoblain/Palabre/compare/v0.1.6...v0.1.7
[0.1.6]: https://github.com/enzoblain/Palabre/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/enzoblain/Palabre/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/enzoblain/Palabre/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/enzoblain/Palabre/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/enzoblain/Palabre/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/enzoblain/Palabre/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/enzoblain/Palabre/releases/tag/v0.1.0
