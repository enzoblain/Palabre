#!/bin/sh
# Commissioning check, run INSIDE a builder VM: fails if a private range or the Mac is reachable, and if the
# internet is not. Usage: check-isolation.sh <mac_ip> [<lan_ip>...]   (see docs/apple-host.md)
# Needs only /bin/sh, curl and nc, which the macOS image ships.
set -eu

[ "$#" -ge 1 ] || { echo "usage: $0 <mac_ip> [<lan_ip>...]" >&2; exit 2; }
TIMEOUT=3
failed=0

# Reachable means the host answered: a connection or a refusal (RST) both prove the packet got through,
# only a silent timeout (a dropped packet) counts as blocked.
reachable() {
    output=$(nc -z -G "$TIMEOUT" "$1" "$2" 2>&1) && return 0
    case "$output" in
        *refused*) return 0 ;;
        *) return 1 ;;
    esac
}

expect_blocked() {
    for port in 22 80 443 5432; do
        if reachable "$1" "$port"; then
            echo "FAIL: $1:$port is reachable from the VM" >&2
            failed=1
        fi
    done
    echo "blocked: $1"
}

# IPv6: pf drops all of it on the VM bridge. Wake the link's neighbours, then probe every link-local neighbour
# (the gateway's among them); none must answer. Without any neighbour there is nothing to probe: say so.
guest_if=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
if [ -n "$guest_if" ]; then
    ping6 -c1 "ff02::1%$guest_if" >/dev/null 2>&1 || true
    neighbours=$(ndp -an 2>/dev/null | awk -v i="$guest_if" '$1 ~ /^fe80:/ && $3 == i {sub(/%.*/, "", $1); print $1}')
    for neighbour in $neighbours; do
        for port in 22 80 443 5432; do
            if nc -6 -z -G "$TIMEOUT" "$neighbour%$guest_if" "$port" >/dev/null 2>&1; then
                echo "FAIL: [$neighbour%$guest_if]:$port is reachable over IPv6 from the VM" >&2
                failed=1
            fi
        done
        echo "blocked (IPv6): $neighbour"
    done
    [ -n "$neighbours" ] || echo "note: no IPv6 neighbour answered, nothing to probe over IPv6"
fi

# The VM's own default gateway is always probed, on top of the given addresses.
gateway=$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}')

# Probes on the Mac and each given LAN address, plus one address of each private range and the link-local one.
for target in "$@" $gateway 10.0.0.1 172.16.0.1 192.168.1.1 169.254.169.254; do
    expect_blocked "$target"
done

for url in https://github.com https://swiftpackageindex.com; do
    if curl -fsS -o /dev/null --max-time 15 -I "$url"; then
        echo "reachable: $url"
    else
        echo "FAIL: $url is not reachable from the VM" >&2
        failed=1
    fi
done

[ "$failed" -eq 0 ] && echo "isolation OK" || { echo "isolation check FAILED" >&2; exit 1; }
