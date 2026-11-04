#!/bin/sh
# Installs the Mac builder worker as a launchd daemon. Idempotent; run with sudo from this directory.
# Usage: sudo ./install.sh   (needs /etc/palabre-apple-worker.toml, see docs/apple-host.md)
set -eu

LABEL=com.palabre.apple-worker
LIB=/usr/local/lib/palabre-apple-worker
PLIST=/Library/LaunchDaemons/$LABEL.plist
CONFIG=/etc/palabre-apple-worker.toml
HERE=$(cd "$(dirname "$0")" && pwd)

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
[ "$(uname -s)" = Darwin ] || { echo "this script is for macOS" >&2; exit 1; }
[ -f "$CONFIG" ] || { echo "missing $CONFIG" >&2; exit 1; }
id palabre >/dev/null 2>&1 || { echo "create the non-admin user 'palabre' first" >&2; exit 1; }
command -v tart >/dev/null 2>&1 || { echo "install Tart first (brew install cirruslabs/cli/tart)" >&2; exit 1; }

# The config holds no secret; the token file it points to must be private to the worker user.
chown root:wheel "$CONFIG"
chmod 644 "$CONFIG"
TOKEN_FILE=$(/usr/bin/python3 -I -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["token_file"])' "$CONFIG")
[ ! -L "$TOKEN_FILE" ] || { echo "$TOKEN_FILE must not be a symlink" >&2; exit 1; }
[ -f "$TOKEN_FILE" ] || { echo "missing token file $TOKEN_FILE" >&2; exit 1; }
chown palabre "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"

mkdir -p "$LIB"
install -m 644 "$HERE/worker.py" "$HERE/vm.py" "$LIB/"
chown -R root:wheel "$LIB"
install -m 644 -o root -g wheel "$HERE/$LABEL.plist" "$PLIST"
touch /var/log/palabre-apple-worker.log
chown palabre /var/log/palabre-apple-worker.log

launchctl bootout system "$PLIST" 2>/dev/null || true
launchctl bootstrap system "$PLIST"
echo "worker started; follow it with: tail -f /var/log/palabre-apple-worker.log"
