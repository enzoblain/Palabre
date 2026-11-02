# Use the apps

**Web app**: open `http://127.0.0.1:2810` on the server itself, or, from another device,
the HTTPS address of your reverse proxy or the private address of the server (for example on
[Tailscale](https://tailscale.com), with `PALABRE_WEB_BIND` set to it, see [Remote access](remote-access.md)),
and enter the `ADMIN_TOKEN` (on first login, the server address is already filled in). Never expose it on the internet.

On first launch, set your name in the settings: it is the one your team calls you by.

**Interface language**: the interface speaks the team language set in the settings (the one
your agents write in), and the login screen uses the last language seen, else the browser's.
French and English are translated; the other team languages show the interface in English.
Texts live in `frontend/src/i18n/` (`en.ts` is the reference, `fr.ts` must have the same keys:
a missing key fails `npm run check`). Names, titles and rules that come from the server's
catalog (roles, company sizes, personalities) and the server's error messages are not translated.

**API errors**: every error of the REST API returns `{"detail": "<English text>", "code": "<snake_case code>"}` with the usual HTTP status. The codes are the values of `ErrorCode` in `backend/app/errors.py` and never change (the text may); `detail` is the fallback when a client has no translation. Request validation errors (422) use `validation_error` with FastAPI's list in `detail`. Domain errors from the workflow and GitHub layers use `workflow_error` (409) and `github_error` (502) unless the raising code names a more specific `ErrorCode` (`WorkflowError(..., code=...)`, `GitHubError(..., code)`); `GitHubError` messages are scrubbed of the token and URL credentials. Unmapped lookups use `not_found`. `code` is absent on Starlette's own 404/405 (unknown route or method): clients must treat it as optional.

**Account quota**: `GET /settings/quota` returns, for each Claude account, what `/usage`
shows in Claude Code: the 5-hour session, the week (all models) and the week per model,
each with the percentage used and its reset time. It is read from Claude's OAuth usage
endpoint with the account's token, which never leaves the backend, and cached for about a
minute. An account that fails returns an `error` without affecting the others.

**Credits exhausted**: when a run fails because the account hit its usage limit or has no
credit left (recognised in the output of `claude -p`, with its reset time when it gives
one, otherwise a 30-minute estimate), the account is paused until then: no new run starts
on it, automatic employees are spread over the other accounts, and the wakeups stay queued
instead of failing (the run does not count as a task failure). The boss gets one line in
#direction per episode ("Claude credits exhausted on account X, work resumes at HH:MM"),
and `GET /orchestrator` lists `exhausted_accounts` for the app. Once the reset has passed
and a run succeeds, the lead is woken with a `credits_back` event (tasks in progress,
queued wakeups) and the boss is told in #direction. The state is kept in memory: after a
restart, the first run that hits the limit rebuilds it.
