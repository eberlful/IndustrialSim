#!/usr/bin/env bash
set -euo pipefail

# Run as root before VS Code opens its sessions as vscode. Using the device's
# numeric group avoids assuming that host and image video/render IDs agree.
for device in /dev/kfd /dev/dri/renderD* /dev/dri/card*; do
    [[ -e "$device" ]] || continue
    device_gid=$(stat -c '%g' "$device")
    device_group=$(getent group "$device_gid" | cut -d: -f1) || device_group=""
    if [[ -z "$device_group" ]]; then
        device_group="gpu-${device_gid}"
        groupadd --gid "$device_gid" "$device_group"
    fi
    usermod --append --groups "$device_group" vscode
done

exec "$@"
