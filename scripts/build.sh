#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project"
python3 scripts/fetch.py
python3 scripts/prepare.py
export CROSS_COMPILE=${CROSS_COMPILE:-aarch64-linux-gnu-}
export KBUILD_BUILD_USER=builder
export KBUILD_BUILD_HOST=ponwrt
export SOURCE_DATE_EPOCH=$(git -C sources/uboot-an758x show -s --format=%ct HEAD)
jobs=${BUILD_JOBS:-6}
make -C build/u-boot O=../tyfza1 CROSS_COMPILE="$CROSS_COMPILE" tyfza1_defconfig
make -C build/u-boot O=../tyfza1 CROSS_COMPILE="$CROSS_COMPILE" -j"$jobs"
mkdir -p output/prototype
cp build/tyfza1/u-boot.bin build/tyfza1/u-boot.dtb output/prototype/
cp source-lock.json output/prototype/
(cd output/prototype && sha256sum u-boot.bin u-boot.dtb source-lock.json > SHA256SUMS)
printf '%s\n' "Compiled prototype: $project/output/prototype/u-boot.bin" \
    'This is a BL33 development artifact, not a flashable Taurus loader.'
