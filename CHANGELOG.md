# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.1] - 2026-10-29

### Fixed

- Creating a project validates `default_branch` and encodes the source branch when creating a branch.
- `BRANCH_PATTERN` rejects a trailing newline.

## [0.6.0] - 2026-10-28

### Added

- Creating a project detects the repository's production branch (the one GitHub declares as default, falling back to `main`, then `master`) instead of assuming one.
- An empty repository is seeded with a first commit holding a minimal README and a `.gitignore`, so tasks can branch from it.
- On its first run on a project, each agent is told to read the README and the tree of the team's branch; later runs only get the branch name.

## [0.5.0] - 2026-10-28

### Added

- A task in review whose PR conflicts with the team's branch, reports no CI after `CI_MISSING_MINUTES` (10 by default), or has a red CI once approved goes back to its dev with the problem, and the team's channel gets a line. One wakeup per head SHA.
- The lead is woken up whenever a task moves (submission, verdict, CI result, sent back), grouped per task within `LEAD_DEBOUNCE_SECONDS` (30), and when a task in progress or in review stays still for `IDLE_TASK_MINUTES` (10), with the reason; agent runs cut by a restart are ignored.
- A task sent back or reassigned wakes its dev, whoever moved it. Putting a task back to `todo` wakes its dev too.
- A task in `todo` or `changes_requested` with no run for `IDLE_TASK_MINUTES` nudges its dev once, then alerts the lead if it still does not start.
- A merge refused because the CI is still running wakes the lead again once the CI is over.
- The `idle_alert_sha`, `stuck_sha`, `unstarted_nudges` and `merge_retry_at` task columns, added automatically at startup. Nothing to do when upgrading.

### Changed

- Pull request CI no longer runs on the `edited` event.

### Fixed

- `assign_task` now really changes the assignee (`get_task` kept showing the old one), and is idempotent.
- The release notes keep the list of changes after the builds attach the downloads to the tag.

## [0.4.0] - 2026-10-28

### Changed

- Release notes list the changes since the previous tag, grouped by Conventional Commit type, before the standard download text of the release workflow.

### Fixed

- CI runs on every push, so task pull requests always have checks and no longer miss them.
- Pull request titles and squash commits end with the pull request number instead of the task number, so the links in release notes point to the right PR.

## [0.3.0] - 2026-10-28

### Added

- Conventional Commits for everything that goes to GitHub: the developer gives `submit_for_review` an English title such as `feat(usage): show real Claude usage per model`, the backend refuses a non-conforming one and adds the task reference. That title is the PR's and the squash commit's.
- Task branches follow the standard `<type>/<id>-<slug>` format (`feat/60-show-real-claude-usage`): the branch starts as `task/<id>` and is renamed at the first submission.
- Semantic Versioning computed from the Conventional Commits merged since the last `vX.Y.Z` tag (`fix`/`perf` patch, `feat` minor, `!` or `BREAKING CHANGE` major, minor while in 0.x). The lead's and DevOps's prompts state the rule.
- `fix_release`, a lead tool that resets the name and notes of a GitHub Release that came out wrong.
- The `tasks.pr_title` column (nullable), added automatically at startup. Nothing to do when upgrading from 0.2.4.

### Changed

- Releases are named `Palabre vX.Y.Z` and carry the same download notes as the release workflow, in English; the release merge commit and PR title are conventional.
- `close_pull_request` never deletes a branch named like a task's (`feat/12-foo`), and task cleanup handles both branch formats.
- Audit of the standards: every backend module has a one-line docstring, and the README, CLAUDE.md and CHANGELOG follow the repository's conventions. The CHANGELOG is rewritten in Keep a Changelog format.

### Fixed

- The release notes, PR title and release merge commit are aligned, including on the decision path.
- The v0.2.3 and v0.2.4 releases are renamed and their notes aligned with the previous releases.

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

### Upgrading from 0.1.x

- Existing projects stay on their current branch. Switching to `dev` is not automatic: use the settings or `set_working_branch`.
- The CEO can only write in `#direction`; a direction channel is created at startup for every existing project.
- Whatever was waiting in the inbox is converted into requests on the first startup.
- Clients of the removed `/notifications` API must be updated.

## [0.1.10] - 2026-10-28

### Fixed

- Repositories are cloned over HTTPS even when given an SSH URL.

## [0.1.9] - 2026-10-28

### Added

- The lead can propose a release that the boss merges in one click.

## [0.1.8] - 2026-10-28

### Fixed

- Typing in the message box is fast again.

### Changed

- The README now explains what Palabre is and how it works.

## [0.1.7] - 2026-10-28

### Added

- The lead can move the team to a working branch.

### Fixed

- The server failing to start in 0.1.6.

## [0.1.6] - 2026-10-28

### Added

- Optional `updater` container for automatic updates.
- The boss can change the branch a project works from.

## [0.1.5] - 2026-10-28

### Added

- QA can record their verdict with `review_task`.

## [0.1.4] - 2026-10-28

### Fixed

- A new project uses the repository's default branch.

## [0.1.3] - 2026-10-28

### Added

- The boss can choose the research rapporteur; it is drawn at random otherwise.

## [0.1.2] - 2026-10-28

### Added

- New `web` service: nginx serves the interface on port 2810 (`PALABRE_WEB_PORT`) and passes `/api` on to the backend, so a phone only needs one address.
- Small screens: a top bar with a menu button, the sidebar slides over the page.
- The release workflow also publishes `ghcr.io/enzoblain/palabre-web`.

### Changed

- In a browser, the connect screen asks for the token only.

### Removed

- The former single-account `CLAUDE_CODE_OAUTH_TOKEN` setting.

## [0.1.1] - 2026-10-28

### Changed

- Task branches are deleted after merge.

## [0.1.0] - 2026-10-28

Initial release.

[Unreleased]: https://github.com/enzoblain/Palabre/compare/v0.6.1...HEAD
[0.6.1]: https://github.com/enzoblain/Palabre/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/enzoblain/Palabre/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/enzoblain/Palabre/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/enzoblain/Palabre/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/enzoblain/Palabre/compare/v0.2.4...v0.3.0
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
