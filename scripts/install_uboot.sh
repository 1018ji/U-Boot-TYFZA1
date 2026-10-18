#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
umask 077

if [ "$#" -gt 2 ] || { [ "$#" -gt 0 ] && [ "$1" != --check ]; }; then
    echo "Usage: sh $0 [--check [boot-backup.bin]]" >&2
    exit 1
fi
for tool in id mkdir rm tail md5sum tar; do
    if ! type "$tool" >/dev/null 2>&1; then
        echo "Required command not found: $tool" >&2
        exit 1
    fi
done
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

# The stock BusyBox has no mktemp. Only clean up a directory we created.
install_dir=/tmp/tyfza1-uboot.$$
if ! mkdir "$install_dir"; then
    echo "Cannot create installer directory: $install_dir" >&2
    exit 1
fi
trap 'rm -rf "$install_dir"' 0
trap 'exit 1' 1 2 15
checksum=$(tail -n +@PAYLOAD_LINE@ "$0" | md5sum)
if [ "${checksum%% *}" != '@PAYLOAD_MD5@' ]; then
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
