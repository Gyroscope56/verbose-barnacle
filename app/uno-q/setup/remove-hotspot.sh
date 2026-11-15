#!/usr/bin/env bash
# Run ON THE UNO Q with sudo to remove the hotspot and restore prior profiles.
set -euo pipefail
PROFILE='parksight-hotspot'
BACKUP='/var/lib/parksight/previous-wifi-autoconnect.tsv'
if [[ $EUID -ne 0 ]]; then
    echo 'Error: Run this script with sudo on the UNO Q.' >&2
    exit 1
fi
if nmcli -g connection.id connection show "$PROFILE" >/dev/null 2>&1; then
    nmcli connection down "$PROFILE" || true
    nmcli connection delete "$PROFILE"
fi
if [[ -f "$BACKUP" ]]; then
    while IFS=$'\t' read -r uuid previous; do
        if nmcli -g connection.id connection show "$uuid" >/dev/null 2>&1; then
            nmcli connection modify "$uuid" connection.autoconnect "$previous"
        fi
    done < "$BACKUP"
    rm -f "$BACKUP"
fi
nmcli radio wifi on
echo 'Hotspot removed. Saved Wi-Fi autoconnect preferences were restored.'
echo 'Reconnect to another Wi-Fi network manually if needed.'
