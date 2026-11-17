#!/bin/sh
# Guest job runner: downloads the job's source, runs `swift build` and `swift test` as an unprivileged user.
# Usage: palabre-job-runner <backend_url> <job_id> <source_url> <commit_sha>, the one-time job token on stdin.
# Exit codes: 0 passed, 10 build or tests broken, 20 infra problem (anything but 0 and 10 is an infra error).
set -eu

EXIT_FAILED=10
EXIT_INFRA=20
BUILD_USER="${PALABRE_BUILD_USER-builder}" # empty means "run as the current user" (tests only)
WORK_ROOT="${PALABRE_WORK_ROOT:-/Users/builder/work}"
DOWNLOAD_TIMEOUT_SECONDS=300

infra_error() {
    echo "palabre-job-runner: $1" >&2
    exit "$EXIT_INFRA"
}

[ "$#" -eq 4 ] || infra_error "usage: palabre-job-runner <backend_url> <job_id> <source_url> <commit_sha>"
backend_url="$1"
job_id="$2"
source_url="$3"
commit_sha="$4"
case "$job_id" in '' | *[!0-9]*) infra_error "invalid job id" ;; esac
case "$commit_sha" in '' | *[!0-9a-f]*) infra_error "invalid commit sha" ;; esac
case "$backend_url" in https://*) ;; *) infra_error "the backend url must use https" ;; esac

IFS= read -r job_token || infra_error "no job token on standard input"
[ -n "$job_token" ] || infra_error "empty job token"

work="$WORK_ROOT/job-$job_id"
rm -rf "$work"
mkdir -p "$work"
bundle="$work.bundle"
trap 'rm -rf "$work" "$bundle"' EXIT

# The token goes to curl through a config on standard input, never in the arguments. The source is served once
# per token, so there is no retry: a failed download is an infra error and the job is queued again.
printf 'header = "Authorization: Bearer %s"\n' "$job_token" |
    curl --silent --show-error --fail --proto '=https' --max-time "$DOWNLOAD_TIMEOUT_SECONDS" \
        --config - --output "$bundle" "${backend_url%/}$source_url" || infra_error "source download failed"
unset job_token

git clone --quiet "$bundle" "$work/src" || infra_error "git clone of the bundle failed"
git -C "$work/src" checkout --quiet --detach "$commit_sha" || infra_error "commit $commit_sha is not in the bundle"

if [ -n "$BUILD_USER" ]; then
    sudo chown -R "$BUILD_USER" "$work"
fi

# The build code (SwiftPM plugins, scripts) runs with an empty environment, so it never sees the token.
run_build() {
    if [ -n "$BUILD_USER" ]; then
        sudo -u "$BUILD_USER" -H /usr/bin/env -i HOME="/Users/$BUILD_USER" PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin" \
            /bin/sh -c 'cd "$1" && swift build && swift test' sh "$work/src"
    else
        (cd "$work/src" && swift build && swift test)
    fi
}

if run_build; then
    exit 0
fi
exit "$EXIT_FAILED"
