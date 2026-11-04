# How it works

## Software company

You create a project on a GitHub repository and pick a company size. Each employee gets
a name, a role and a personality drawn at random (risk-taking, taste for new technologies,
speed vs quality...), or you build the team yourself.

| Size | People | Rules before a merge |
|---|---|---|
| Startup | 4 | One review approval |
| Scale-up | 8 | One review approval and a QA pass |
| Enterprise | 12 | Plus security on sensitive PRs, and a green CI |
| Multinational | 16 | Two approvals, QA, security, CI, updated docs (README or `docs/`), and your validation of every decision |

You only talk to the lead, in `#direction`: it is the one channel you can write in, and
it holds only you and the lead. The team works in its own channels (`#dev`,
`#quality`...) and the lead can open more (`create_channel`: `#backend`, `#front`...).
You see no other conversation: the API hides the team channels and the DMs from you (404; you cannot create a channel either), and only
the lead is woken by what you post. Tasks and their reviews stay visible as tasks. What you do see is whether each employee is busy or
available (`GET /projects/{id}/presence`). `GET /projects` also gives each project an `unread_count` (the lead's messages in direction after your read position; your own messages and automatic lines do not count), `last_message` (the latest message of direction: `content`, `author`, `created_at`; `null` when there is none) and `lead_writing` (the lead has a run open in direction, for a "typing" indicator); `POST /projects/{id}/direction/read` moves the read position to the last message and returns the project with `unread_count` 0. The lead relays between direction and
the team, and posts in direction only what needs your attention. Employees also have DMs
(`@Name`, one per pair, never with you as a participant): a DM is for an exchange between two people, a channel
for anything that concerns several, and decisions never stay in a DM. At each wakeup an
employee is told which channels and DMs they are in. DMs stay forever: nothing deletes or
expires them, and the admin API refuses to delete one. Existing projects get their
`#direction` channel at startup. There is no catch-all channel. A team you build by hand
starts with only `#direction`; a single Claude call (`company/channel_planner.py`, in the
background) then proposes its channels, and the catalog's channels are used if that fails.

At startup, existing projects lose their old generic channels (`#general`, `#engineering`,
`#product`, `#equipe`, `#couts-claude`) with their messages. The rule is the kind (a channel,
never a DM or `#direction`) and the name, unless the catalog targets that name; membership
does not matter. Their tasks, decisions (releases included) and open questions move to
`#direction` first. `#direction`, targeted channels and all DMs are kept. This runs once, guarded by a marker in the app
settings: a `#product` created afterwards survives restarts.

The research groups feature was removed (it is kept on the `archive/research` branch). At startup, any leftover research project is deleted with its data, and the columns that only served it (`kind`, `topic`, `research_phase` of `projects`) are dropped; company projects are untouched.

From there the team works on its own:

1. **The lead** splits the work into tasks with acceptance criteria and assigns them.
   The lead's prompt has a "Reviewing the team" section: the members with their role and mission, and a cue per role (designer before any screen, security for auth and data...). The lead goes through them on every boss message and before creating or assigning a task. Only the roles present in the team are listed.
2. **A developer** works on the task in its own git clone (made from the project's clone with `--reference --dissociate`, so it never writes to it; the token never reaches a clone: GitHub is fetched and pushed from the project's clone, and agent clones only talk to it locally), then opens a pull request. The branch starts as `task/<id>` and, at the first
   `submit_for_review`, is renamed `<type>/<id>-<slug>` (`feat/60-show-real-claude-usage`) from the title below, before the push.
   Everything that goes to GitHub is in English, whatever the team's language, in
   [Conventional Commits](https://www.conventionalcommits.org) format: the developer gives
   `submit_for_review` a title such as `feat(usage): show real Claude usage per model`, the backend
   refuses a non-conforming one and never adds a number to it: a trailing `(#N)` is dropped, and the backend appends the PR number exactly once to the squash commit title when merging (`... (#82)`; never the task number, which GitHub would read as another PR). That title is the PR's and
   the squash commit's; the PR body says `Palabre task #60`. Review and QA comments and release notes are in English too (release notes keep the standard text, not Conventional Commits bullets).
3. **Reviewers, QA and security** read the diff and approve or request changes, as the
   company's rules require.
   `get_diff` returns the `Head:` commit, the stat and the diff. Lockfiles (`package-lock.json`, `yarn.lock`, `uv.lock`, `Cargo.lock`... see `LOCKFILE_NAMES` in `diff_view.py`) are listed with their added and removed line counts but their content is not shown, whether the file is modified or newly added (a new 16,000-line `package-lock.json` is summarised like an edit, so the files after it stay visible); the note tells the reader to review dependency changes in the file, and quotes the added lines (up to 10 per file) whose URL is outside `DEFAULT_REGISTRY_PREFIXES` (npm, PyPI, crates.io, RubyGems, Packagist, Go proxy) and `DEFAULT_REGISTRY_URLS` (exact URLs on hosts that serve arbitrary content, such as the crates.io index on GitHub), so a swapped `resolved`/`source` stays visible (Cargo's `registry+`/`sparse+` markers are ignored). Sources without a `scheme://` are always quoted: `git@host:org/repo`, and the `github:`, `gitlab:`, `bitbucket:`, `gist:`, `file:`, `link:`, `portal:`, `exec:` and `patch:` shorthands. Known limit: `go.sum` has no URL, so its module paths are not checked. The diff is cut by whole files at 100,000 characters: a file that does not fit is left out and named in a closing note, and the files after it are still shown.
   Security's approval is required (where the company has the gate) for a PR on a sensitive path, or for a task the lead marked `sensitive` with `create_task` / `update_task`; see [Security](security.md).
4. **The lead** merges once every rule is met. Nothing reaches the project's branch otherwise.
   On an Apple project, the Swift build of the PR head must also have passed, whatever the company's size; an infra error is shown apart from a failing build and can be retried (see [Apple mode](apple-mode.md)).

The platform keeps the lead on track. Every step of a task (pull request submitted, each
review, QA or security verdict with its author, merge) is announced by a short "Palabre"
line in the task's channel, with the link. As soon as a task meets every merge rule of the
company's size, the lead is woken up to merge it,
and reminded once if it is still not merged after `MERGE_REMINDER_MINUTES` (10 by default).
The same goes for releases: when the CI of the open release PR (team's branch to production) ends,
and, after `merge_release`, when the CI of production's head ends, the lead is woken up once per
head SHA with the result (green, or the failing checks) and a "Palabre" line is posted in the
team's first channel. Green means `merge_release`, then `publish_version`: once production's CI is green, the wakeup says which version to publish ("publish vX.Y.Z").
No release depends on the lead remembering it: when the team's branch holds commits production lacks, no task is open and nothing moved for `RELEASE_WAIT_MINUTES` (5 by default), the lead is woken (`release_pending`, once per head SHA, stored in `Project.release_reminded_sha`) with the pending changes and the computed version.

A resubmission whose content is unchanged (the reviewed commit replayed with `git merge-tree` on the base the branch now sits on gives exactly the new tree, i.e. a pure rebase) keeps the review round and its approvals, unless a reviewer's latest verdict of the round asks for changes or the task newly becomes sensitive; the merge still waits for the CI of the new head. A pure rebase keeps the approvals even if the new base changes the behavior indirectly; the CI on the new head is then the only safeguard. Any content change starts a new round and drops every approval. The `refs/palabre/reviewed/{id}` ref that pins the reviewed commit is deleted when the task is merged or cancelled.

A task stuck in review does not wait for someone to notice: if its PR conflicts with the team's
branch, if no CI check is reported `CI_MISSING_MINUTES` (10 by default) after the submission, or if
the CI is red on an otherwise approved task, the task goes back to its dev (`changes_requested`)
with the problem (rebase, missing CI, failing checks) and a "Palabre" line is posted in the team's
first channel. The dev is woken up once per head SHA. A red CI only sends the task back once it is
otherwise approved (no other merge rule is missing); before that, reviewers go first.
A red check comes with its annotations and summary, framed as untrusted CI output (at most 20 annotations and 4,000 characters, plain text, fetched by the backend; agents never see the token), in `merge_blockers`, the dev's wakeup and the lead's wakeups; the team channel only gets the first line.

The lead is also woken up (`task_update`) whenever a task moves: PR submitted or resubmitted, each
review verdict, CI finished, task sent back. Changes of the same task within
`LEAD_DEBOUNCE_SECONDS` (30 by default) are grouped into one wakeup sent when the window ends, listing them all. A watchdog alerts the lead
(`task_idle`, once per head SHA) when a task in progress or in review has not moved for
`IDLE_TASK_MINUTES` (10 by default), with the reason: conflict, missing or red CI, missing review,
or simply no activity.

A task never waits silently for its dev either: putting a task back to `todo` (with or without a PR:
rebase, new work), requesting changes, or calling `assign_task` (also to the same dev, which then
only nudges) wakes the assignee with the reason, unless a run or a wakeup is already on that
task. A `todo` or `changes_requested` task whose dev has had no run for `IDLE_TASK_MINUTES` is
nudged once; if it still does not start after another `IDLE_TASK_MINUTES`, the lead is alerted
(`task_idle`). Tasks waiting for their dependencies are left alone. When `merge_task` is refused
because the CI is still running, the lead is woken (`merge_retry`) as soon as the CI is over,
or as a mergeable task if every rule is then met.

A run that ends without error while its task is still `in_progress` (or `changes_requested`) with no
PR wakes the same dev again right away (`task_stalled`), unless a run or wakeup is already on the
task. As a safety net, the scheduler does the same for a task whose dev has had no run or wakeup for
`STALLED_TASK_MINUTES` (5 by default), for instance after a backend restart. Failed runs keep their
own retries. After `MAX_STALLED_RESTARTS` (3 by default) restarts the lead is woken once
(`task_run_failed`) instead of looping; any wakeup by someone else resets the count.

A task never waits silently for its reviewer either: when QA or security post a report on a task in
review, a reviewer whose last opinion is a comment without a verdict is woken up (`verification_done`)
to give approve or changes. As a safety net, a task in review with no reviewer verdict for
`REVIEW_SILENCE_MINUTES` (15 by default) wakes the reviewers again (`review_overdue`, when none is
busy) and tells the lead (`review_stalled`), then waits another delay before the next reminder.
Reminders are capped per head SHA by `MAX_REVIEW_REMINDERS` (3 by default, QA and security reports
included); past it the lead gets one last notification (`review_abandoned`). A new head starts again from zero.

Finished tasks clean up after themselves: once a task is merged or cancelled, the backend
closes its PR if still open and deletes its branch (`task/<id>...` or `<type>/<id>-<slug>`, on GitHub) and its
clone. Only branches recorded on tasks are touched, never the default branch, `dev` or a
release PR. To clean the backlog, call `POST /api/tasks/cleanup` (admin token): it is idempotent
and GitHub errors (404...) are only logged.

Agents that keep pinging each other are throttled: past `MAX_RUNS_PER_CONVERSATION_HOUR` (default 20)
executed chatter runs of one employee within an hour, across all their conversations (skipped
wakeups do not count), the lead is alerted. Their chatter wakeups (mentions...) are not lost:
they stay queued and run grouped in one run once the window frees a slot. The boss posting in a
conversation lifts the limit there, or call `POST /api/conversations/{id}/lift-rate-limit` (admin
token, `204`): earlier runs stop counting and held wakeups of that conversation run right away
(those held in other conversations keep waiting). The reset is kept in memory, so a backend restart forgets it.

Along the way the team holds a daily stand-up, records decisions in each room's shared
document, and asks you when something is yours to decide. There is no inbox: the lead puts
what waits for you in the direction channel as a request: a normal message from the lead, with
no button. You answer in plain words, like in any chat. Your next message in direction closes every
request still waiting (status `answered`, your message as comment, so none stays open) and wakes the
lead up with your reply and the requests it answers (`ceo_answer`); the lead interprets it ("ok" is a
yes, a condition is not) and acts. For a decision the lead records the outcome with `settle_decision`
(`validated` or `rejected`); `validated` is refused while the decision has requests in direction and the boss has answered none of them.
Proposed decisions, releases and escalations to the boss become such requests on their own. A decision the boss already took in the conversation is recorded by the lead with `add_decision(decided_by_boss=True)`: it is saved `validated` right away, with no request in direction (any other role is refused). Only the lead speaks in direction: a request from another member is signed by the lead, who owns it, without that member's name in the text (the app keeps who it is for). A decision shows its title and its whole rationale. Every request the boss reads (decisions, escalations, `ask_ceo`, releases) is written for a non-developer: plain sentences, no jargon, no code references (files, identifiers, task or PR numbers); the technical detail stays in the room document or the task. Every agent gets this rule ("Messages to the boss") in its prompt.
The lead can ask for anything else with `ask_ceo`. The lead keeps the list short. `list_pending_requests` shows their requests still waiting. `withdraw_request` drops one that became useless (status `withdrawn`, with a reason). `merge_requests` replaces several by one new request: they become `merged`, pointing to it via `request_merged_into`. An answered request cannot be withdrawn or merged. A request relayed for a member keeps its real author in `request_author_id`; an escalation relayed that way (`escalate(to="boss")`) can be neither withdrawn nor merged by the lead, only the boss answers it, by replying in the chat. Withdrawing a relayed decision rejects it with a reason saying the boss did not answer. A request linked to a decision cannot be merged, and withdrawing it rejects the decision with the reason. A release request can be neither merged nor withdrawn.
On upgrade, what waited in the old
inbox is turned into requests in direction.

A new project works on a `dev` branch, created from the repository's default branch if
missing (an empty repository gets its default branch, `main` unless GitHub says otherwise, then `dev`, from a first commit with a minimal README and `.gitignore`). The production branch is the one GitHub declares as default (`main`, `master` or another; failing that `main`, then `master`), never assumed. Every agent is told to read the README and the tree of the team's branch first, and every
task's pull request targets it. Only a release reaches production. To switch an existing
project, point it at `dev` on the project's Infos page, or ask the lead to run `set_working_branch`
(`dev`); open pull requests are retargeted. When a step is ready, the lead opens the pull
request from `dev` to production and asks you in direction. You answer in the chat: when you say yes the lead
ships it with `merge_release`, when you say no the lead closes it with `settle_decision` (`rejected`), and
anything else is a request to rework it. Without your go the lead does not merge into the
repository's default branch. If the team's branch is deleted on GitHub (for
instance with "Delete branch" after merging the release pull request), the backend recreates it
from production at the next sync and posts a system line in the direction channel to tell you. To prevent the deletion, add a ruleset on GitHub that blocks
deleting `dev`.

The lead can also deliver alone. `merge_release` merges the release pull request once CI is
green on it, whatever the company size, and only if the PR has not moved since (a task
merged meanwhile makes GitHub refuse), and tells you in direction, with nothing to answer; `publish_version`
tags the head of the default branch `vX.Y.Z` (CI must be green on it) and publishes the GitHub Release (named `Palabre vX.Y.Z`, with the changes since the previous tag grouped by type, then the download text of the release
workflow), which starts that workflow; `fix_release` regenerates the name and notes of an existing release the same way. The sections are Breaking Changes, Features (`feat`), Bug Fixes (`fix`), Performance (`perf`), Documentation (`docs`) and Other (everything else, old non-conventional commits included), one `scope: description (#PR)` line per commit. Versions follow [Semantic Versioning 2.0.0](https://semver.org), computed from the
Conventional Commits merged since the last `vX.Y.Z` tag: `fix` and `perf` bump the patch, `feat` the minor,
a `!` or a `BREAKING CHANGE` footer the major (while in 0.x, a breaking change bumps the minor); the highest bump
wins. When commits follow the last tag but none requests a bump (only `ci`, `chore`, `docs`...), the release is a corrective patch (0.30.0 -> 0.30.1) and the CHANGELOG lists them under Chores; with no conventional commit since the tag (none at all, or only non-conventional messages), the release is still refused. The lead's and DevOps's prompts state the rule. `publish_version` refuses a version that is not `X.Y.Z`, a tag that
already exists, or a version that differs from `frontend/package.json`, its lock or `docker-compose.yml` (the bump is made for you). Releases need no bump task: `merge_release` first computes the next version with the rule above from the commits since the last tag, and the backend commits `chore(release): X.Y.Z` on the team's branch only (never on production, no force push), in one commit made in its local clone: `frontend/package.json` and `package-lock.json` and `docker-compose.yml` (edited directly, no npm on the server), and the Keep a Changelog entry under `[Unreleased]` (it replaces whatever `[Unreleased]` held, and any entry of a version never released: nobody edits the CHANGELOG by hand, the developers' prompts say so; `feat` Added, `fix` Fixed, `perf` and `refactor` Changed, breaking changes flagged; chores and docs are left out, unless nothing else changed: they then fill a Chores section). It is recomputed on every call (a commit merged after the bump joins the entry, and the version follows the bump level) and commits only if a file changes, never an empty commit. It refuses a version file whose format it does not know. After a commit the release PR's CI restarts: the lead is woken once it ends, then calls `merge_release` again, which merges under the usual CI gate. Both tools are the lead's only (`ship_release` permission in
the catalog); `propose_release` and your chat reply stay available when the lead wants your opinion.

The lead also triages pull requests no task owns, such as Dependabot's: `list_pull_requests`
shows every open one, and `close_pull_request` closes one with a comment and deletes its
branch. It refuses a task's pull request (cancel the task instead) and the release one, and
never deletes production, the team's branch or a fork's branch, nor a branch named like a task's (`feat/12-foo`).

## Research group

You give a topic instead of a repository. A group of peers of equal standing, each with
their own angle (explorer, skeptic, data analyst, devil's advocate, historian...), works
on every question you ask in four phases:

1. **Research**: everyone searches the web and posts sourced findings.
2. **Debate**: they confront their findings.
3. **Conclusion**: each one states a final position.
4. **Report**: the rapporteur writes it up: the short answer, the key findings with their
   sources, the disagreements and the open questions. You read it in the Report tab, which
   is also where the proposed conclusions are validated. Company projects have no such tab.

Groups come in three sizes: Duo (2), Panel (5) and Council (9). You choose the rapporteur,
or leave it to chance.
