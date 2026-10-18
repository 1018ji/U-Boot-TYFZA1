#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
umask 077

if [ "$#" -gt 2 ] || { [ "$#" -gt 0 ] && [ "$1" != --check ]; }; then
    echo "Usage: sh $0 [--check [boot-backup.bin]]" >&2
    exit 1
fi
if [ "$#" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer as root." >&2
    exit 1
fi
if [ "$#" -eq 2 ]; then
    case "$2" in
        /*) boot_backup=$2 ;;
        *) boot_backup=$PWD/$2 ;;
    esac
fi

install_dir=$(mktemp -d /tmp/tyfza1-uboot.XXXXXX)
trap 'rm -rf "$install_dir"' 0
trap 'exit 1' 1 2 15
checksum=$(tail -n +@PAYLOAD_LINE@ "$0" | sha256sum)
if [ "${checksum%% *}" != '@PAYLOAD_SHA256@' ]; then
    echo "Installer checksum failed; copy the complete file again." >&2
    exit 1
fi
tail -n +@PAYLOAD_LINE@ "$0" | tar -xz -C "$install_dir" \
    tyfza1-flash-uboot tyfza1-uboot-universal.bin

# Keep the boot backup outside the temporary extraction directory.
cd /tmp
case "$#" in
    0) "$install_dir/tyfza1-flash-uboot" "$install_dir/tyfza1-uboot-universal.bin" ;;
    1) "$install_dir/tyfza1-flash-uboot" --check "$install_dir/tyfza1-uboot-universal.bin" ;;
    2) "$install_dir/tyfza1-flash-uboot" --check "$install_dir/tyfza1-uboot-universal.bin" "$boot_backup" ;;
esac
exit 0
__TYFZA1_PAYLOAD__
