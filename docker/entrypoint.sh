#!/usr/bin/env bash
set -euo pipefail

# Device groups come from the host and may differ from those in the image.
for device in /dev/kfd /dev/dri/renderD* /dev/dri/card*; do
    [[ -e "$device" ]] || continue
    device_gid=$(stat -c '%g' "$device")
    device_group=$(getent group "$device_gid" | cut -d: -f1) || device_group=""
    if [[ -z "$device_group" ]]; then
        device_group="gpu-${device_gid}"
        groupadd --gid "$device_gid" "$device_group"
    fi
    usermod --append --groups "$device_group" industrialsim
done

exec gosu industrialsim "$@"
