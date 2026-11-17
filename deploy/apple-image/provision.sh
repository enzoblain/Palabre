#!/bin/sh
# Runs once in the VM while Packer builds the image: build tools, the unprivileged build user, the job runner.
# The image holds no secret: the job token only arrives on the runner's standard input.
set -eu

BUILD_USER=builder
RUNNER=/usr/local/bin/palabre-job-runner

if ! id "$BUILD_USER" >/dev/null 2>&1; then
    sudo sysadminctl -addUser "$BUILD_USER" -password "$(openssl rand -base64 24)" -home "/Users/$BUILD_USER" >/dev/null
fi
sudo mkdir -p "/Users/$BUILD_USER/work"
sudo chown -R "$BUILD_USER" "/Users/$BUILD_USER"
sudo chmod 700 "/Users/$BUILD_USER"

# Versions follow the pinned base image; the image itself is pinned by digest in APPLE_IMAGE.
brew install swiftlint xcbeautify

sudo install -m 755 -o root -g wheel /tmp/palabre-job-runner "$RUNNER"
rm -f /tmp/palabre-job-runner

# No credential may stay in the image: shell history, git config, keychain items of the setup session.
rm -f "$HOME/.zsh_history" "$HOME/.bash_history" "$HOME/.git-credentials"
sudo -u "$BUILD_USER" -H git config --global --list 2>/dev/null | grep -qi 'credential\|token' && exit 1
"$RUNNER" 2>&1 | grep -q usage
