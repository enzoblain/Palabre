#!/bin/sh
# Installs the Mac builder worker as a launchd daemon. Idempotent; run with sudo from this directory.
# Usage: sudo ./install.sh   (needs /etc/palabre-apple-worker.toml, see docs/apple-host.md)
set -eu

LABEL=com.palabre.apple-worker
LIB=/usr/local/lib/palabre-apple-worker
PLIST=/Library/LaunchDaemons/$LABEL.plist
CONFIG=/etc/palabre-apple-worker.toml
PF_LABEL=com.palabre.apple-pf
PF_PLIST=/Library/LaunchDaemons/$PF_LABEL.plist
PF_ANCHOR=palabre/apple-vm
PF_ANCHOR_FILE=/etc/pf.anchors/palabre-apple-vm
SUDOERS=/etc/sudoers.d/palabre-apple-pf
# Tart's default shared network; override for another one: VM_NET=... VM_GATEWAY=... VM_IF=... sudo -E ./install.sh
VM_NET=${VM_NET:-192.168.64.0/24}
VM_GATEWAY=${VM_GATEWAY:-192.168.64.1}
VM_IF=${VM_IF:-bridge100}
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

# Second network barrier (after Tart's softnet): a pf anchor that blocks the private ranges and the Mac itself
# from the VM subnet. The Mac's addresses are written into the anchor now, so run this again if one changes.
MAC_IPS=$(ifconfig | awk '/^[[:space:]]inet /{print $2}' | grep -v '^127\.' | paste -sd, - | sed 's/,/, /g')
[ -n "$MAC_IPS" ] || { echo "could not find the Mac's IP addresses" >&2; exit 1; }
sed -e "s|\$vm_net|$VM_NET|g" -e "s|\$vm_gateway|$VM_GATEWAY|g" -e "s|\$vm_if|$VM_IF|g" -e "s|\$mac_ips|{ $MAC_IPS }|g" \
    "$HERE/com.palabre.apple-vm.pf.conf" > "$PF_ANCHOR_FILE.new"
chmod 644 "$PF_ANCHOR_FILE.new"
/sbin/pfctl -n -a "$PF_ANCHOR" -f "$PF_ANCHOR_FILE.new" || { rm -f "$PF_ANCHOR_FILE.new"; echo "invalid pf anchor, nothing changed" >&2; exit 1; }
mv "$PF_ANCHOR_FILE.new" "$PF_ANCHOR_FILE"
chown root:wheel "$PF_ANCHOR_FILE"
if ! grep -q "anchor \"$PF_ANCHOR\"" /etc/pf.conf; then
    [ -f /etc/pf.conf.palabre-backup ] || cp /etc/pf.conf /etc/pf.conf.palabre-backup
    printf 'anchor "%s"\nload anchor "%s" from "%s"\n' "$PF_ANCHOR" "$PF_ANCHOR" "$PF_ANCHOR_FILE" >> /etc/pf.conf
fi
/sbin/pfctl -n -f /etc/pf.conf || { echo "invalid /etc/pf.conf; restore /etc/pf.conf.palabre-backup" >&2; exit 1; }
install -m 644 -o root -g wheel "$HERE/$PF_LABEL.plist" "$PF_PLIST"
# Load and enable pf now, synchronously; the daemon below only reloads it at each boot.
/sbin/pfctl -E -f /etc/pf.conf
launchctl bootout system "$PF_PLIST" 2>/dev/null || true
launchctl bootstrap system "$PF_PLIST"
# The worker (user palabre) may only read this anchor and the pf status to prove they are active, nothing else.
printf 'palabre ALL=(root) NOPASSWD: /sbin/pfctl -a %s -s rules, /sbin/pfctl -s info\n' "$PF_ANCHOR" > "$SUDOERS.new"
/usr/sbin/visudo -cf "$SUDOERS.new" >/dev/null || { rm -f "$SUDOERS.new"; echo "invalid sudoers entry" >&2; exit 1; }
chmod 440 "$SUDOERS.new"
mv "$SUDOERS.new" "$SUDOERS"
sudo -u palabre sudo -n /sbin/pfctl -a "$PF_ANCHOR" -s rules | grep -q palabre-apple-vm-private \
    || { echo "the pf anchor is not active after loading" >&2; exit 1; }
sudo -u palabre sudo -n /sbin/pfctl -s info | grep -q "Status: Enabled" \
    || { echo "pf is not enabled after loading" >&2; exit 1; }
echo "pf anchor $PF_ANCHOR active for $VM_NET (Mac addresses: $MAC_IPS)"

mkdir -p "$LIB"
install -m 644 "$HERE/worker.py" "$HERE/vm.py" "$LIB/"
chown -R root:wheel "$LIB"
install -m 644 -o root -g wheel "$HERE/$LABEL.plist" "$PLIST"
touch /var/log/palabre-apple-worker.log
chown palabre /var/log/palabre-apple-worker.log

launchctl bootout system "$PLIST" 2>/dev/null || true
launchctl bootstrap system "$PLIST"
echo "worker started; follow it with: tail -f /var/log/palabre-apple-worker.log"
