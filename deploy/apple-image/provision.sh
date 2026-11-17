#!/bin/sh
# Runs once in the VM while Packer builds the image: build tools, the unprivileged build user, the job runner.
# The image holds no secret: the job token only arrives on the runner's standard input.
set -eu

BUILD_USER=builder
RUNNER=/usr/local/bin/palabre-job-runner
WORK_ROOT=/private/tmp/palabre-work # must match the runner default

if ! id "$BUILD_USER" >/dev/null 2>&1; then
    sudo sysadminctl -addUser "$BUILD_USER" -password "$(openssl rand -base64 24)" -home "/Users/$BUILD_USER" >/dev/null
fi
sudo chown -R "$BUILD_USER" "/Users/$BUILD_USER"
sudo chmod 700 "/Users/$BUILD_USER"
# The runner (admin) owns the work root; the build user only traverses it and gets its own job folder by chown.
mkdir -p "$WORK_ROOT"
chmod 755 "$WORK_ROOT"

# Not pinned: these tools follow Homebrew at build time, so two builds of the image can differ; the base image is pinned by digest.
brew install swiftlint xcbeautify

sudo install -m 755 -o root -g wheel /tmp/palabre-job-runner "$RUNNER"
rm -f /tmp/palabre-job-runner

# No credential may stay in the image: shell history, git config, keychain items of the setup session.
rm -f "$HOME/.zsh_history" "$HOME/.bash_history" "$HOME/.git-credentials"
sudo -u "$BUILD_USER" -H git config --global --list 2>/dev/null | grep -qi 'credential\|token' && exit 1
"$RUNNER" 2>&1 | grep -q usage

# Last step: the admin account gets a random password nobody keeps. Packer's SSH session (admin/admin) is already open and the
# image build needs no other login; tart exec does not use the password, and sudo stays passwordless for the runner.
sudo dscl . -passwd "/Users/$(id -un)" "$(openssl rand -base64 24)"
