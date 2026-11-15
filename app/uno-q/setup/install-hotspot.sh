#!/usr/bin/env bash
# Run ON THE ARDUINO UNO Q's Debian Linux shell (not on macOS):
#   sudo bash /tmp/install-hotspot.sh
# This is a ONE-TIME configuration. NetworkManager brings the AP up on boot.
set -euo pipefail

SSID='ParkSight-UNOQ'
PROFILE='parksight-hotspot'
IP='10.42.0.1/24'
STATE_DIR='/var/lib/parksight'
BACKUP="$STATE_DIR/previous-wifi-autoconnect.tsv"

if [[ $EUID -ne 0 ]]; then
    echo 'Error: Run this script with sudo on the UNO Q.' >&2
    exit 1
fi
PASSWORD="${PARKSIGHT_HOTSPOT_PASSWORD:-}"
if [[ -z "$PASSWORD" && -t 0 ]]; then
    read -rsp "Hotspot password (8–63 characters): " PASSWORD
    echo
fi
if (( ${#PASSWORD} < 8 || ${#PASSWORD} > 63 )); then
    echo 'Set PARKSIGHT_HOTSPOT_PASSWORD or enter an 8–63 character password.' >&2
    exit 1
fi
if ! command -v nmcli >/dev/null 2>&1; then
    echo 'Error: NetworkManager (nmcli) was not found on the UNO Q.' >&2
    exit 1
fi

# Prefer the UNO Q's usual interface but support a different Wi-Fi name.
IFACE="${PARKSIGHT_WIFI_IFACE:-}"
if [[ -z "$IFACE" ]]; then
    IFACE="$(nmcli -t -f DEVICE,TYPE device status | awk -F: '$2 == "wifi" { print $1; exit }')"
fi
if [[ -z "$IFACE" ]]; then
    echo 'Error: No Wi-Fi interface found. Check `nmcli device` and firmware.' >&2
    exit 1
fi

echo "Configuring persistent Wi-Fi access point on $IFACE ..."
nmcli radio wifi on
if ! nmcli -g connection.id connection show "$PROFILE" >/dev/null 2>&1; then
    nmcli connection add type wifi ifname "$IFACE" con-name "$PROFILE" ssid "$SSID"
fi

nmcli connection modify "$PROFILE" \
    connection.interface-name "$IFACE" \
    connection.autoconnect yes \
    connection.autoconnect-priority 100 \
    802-11-wireless.ssid "$SSID" \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.psk "$PASSWORD" \
    ipv4.method shared \
    ipv4.addresses "$IP" \
    ipv6.method disabled

# Test before disabling previous Wi-Fi profiles so a failure doesn't remove
# all network connectivity. USB ADB remains available in either case.
if ! nmcli connection up "$PROFILE" ifname "$IFACE"; then
    echo 'Hotspot activation failed. Existing Wi-Fi autoconnect was not changed.' >&2
    echo 'Check: nmcli device; journalctl -u NetworkManager -n 60' >&2
    exit 1
fi

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
if [[ ! -e "$BACKUP" ]]; then
    : > "$BACKUP"
    chmod 600 "$BACKUP"
    while IFS=: read -r uuid type; do
        case "$type" in wifi|802-11-wireless) ;; *) continue ;; esac
        if [[ "$(nmcli -g connection.id connection show "$uuid")" == "$PROFILE" ]]; then
            continue
        fi
        previous="$(nmcli -g connection.autoconnect connection show "$uuid")"
        printf '%s\t%s\n' "$uuid" "$previous" >> "$BACKUP"
    done < <(nmcli -t -f UUID,TYPE connection show)
fi
# This device is intentionally offline: do not reconnect to campus/venue Wi-Fi
# after reboot. The installer preserves old settings in BACKUP for reversal.
while IFS=: read -r uuid type; do
    case "$type" in wifi|802-11-wireless) ;; *) continue ;; esac
    if [[ "$(nmcli -g connection.id connection show "$uuid")" != "$PROFILE" ]]; then
        nmcli connection modify "$uuid" connection.autoconnect no
    fi
done < <(nmcli -t -f UUID,TYPE connection show)

echo
echo 'Hotspot is active and will reconnect automatically after reboot.'
echo "SSID:     $SSID"
echo 'URL:      http://10.42.0.1:5001/'
echo 'NOTE: The web page is available only when the ParkSight App is running.'
echo 'For automatic web startup, enable "Run at startup" for ParkSight in App Lab.'
echo 'Verify: nmcli -f GENERAL,IP4 device show '"$IFACE"
