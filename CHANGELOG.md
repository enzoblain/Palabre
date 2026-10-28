# Changelog

## 0.2.3

### Highlights

- **Real Claude usage per model**: the settings Usage screen works like `/usage`, per account and per model, from the accounts' real usage.
- **Lead wake-up on mergeable tasks**: the lead is woken up when a task can be merged, and reminded once if it waits too long. The orchestrator also announces its steps in the chat.

### Also in this release

- System lines from "Palabre" now look like the boss's messages.
- Usage tracking hardening: httpcore logs and a lock on the cache.

### Upgrading from 0.2.2

- Nothing to do: the `merge_ready_at` and `lead_reminded_at` task columns are added automatically at startup.

## 0.2.2

- **Unread badges in direction only**: team channels no longer show a new-message count (the live dot stays), and the app stops polling them for it.

## 0.2.1

### Highlights

- **Outside pull requests**: the lead triages the PRs no task owns, such as Dependabot's. `list_pull_requests` shows every open PR with its task, and `close_pull_request` closes one with a comment and deletes its branch. A task's PR, the release PR, production, the team's branch and forks' branches are left alone.

### Upgrading from 0.2.0

- Nothing to do: the lead gets the two tools on restart.

## 0.2.0

### Highlights

- **`dev` by default**: every new project works on a `dev` branch. Task PRs target `dev`, and a release PR from `dev` to `main` ships the work.
- **Channels**: the CEO only talks to the lead, in `#direction`. Team channels are read-only for the CEO, who follows them live, and the lead can open new ones (`create_channel`).
- **Interactive messages**: the lead's messages can carry Validate / Reject / Nuance buttons, so the CEO answers a decision or proposal in one click.
- **Inbox removed**: what used to wait in the inbox is now a request in `#direction`, and escalations show up where they were written.
- **Usage in settings**: the settings page shows the Claude account usage.

### Also in this release

- The lead can merge releases, tag and publish versions. The merge is pinned to the checked commit and requires green CI before tagging.
- Task branches are cleaned up automatically after a merge or a cancellation. `POST /api/tasks/cleanup` cleans up the existing leftovers.

### Upgrading from 0.1.x

- Existing projects stay on their current branch. Switching to `dev` is not automatic: use the settings or `set_working_branch`.
- The CEO can only write in `#direction`. A direction channel is created at startup for every existing project.
- Whatever was waiting in the inbox is converted into requests on the first startup.
- The `/notifications` API is removed: clients that use it will break.
