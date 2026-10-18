#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
out=${1:-$project/output/tyfza1-flash-uboot}
mkdir -p "$(dirname "$out")"
${CC:-cc} -Os -static -ffunction-sections -fdata-sections -Wl,--gc-sections \
    -Wall -Wextra -Werror -I"$project/overlay/board/realtek/tyfza1" \
    "$project/tools/flash_uboot.c" "$project/overlay/board/realtek/tyfza1/formats.c" \
    "$project/overlay/board/realtek/tyfza1/certificates.c" \
    "$project/tests/certificate_openssl.c" -lcrypto -ldl -pthread -o "$out"
strip "$out"
