#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project"
for variant in 4ge 2p5g; do
    python3 scripts/package_loader.py --stock-boot "inputs/$variant-boot.bin" --output "output/candidate-$variant"
done
mkdir -p output/release
python3 scripts/package_universal.py \
    --4ge output/candidate-4ge/taurus_spi_nand_loader.img \
    --2p5g output/candidate-2p5g/taurus_spi_nand_loader.img \
    --stock-4ge inputs/4ge-boot.bin --stock-2p5g inputs/2p5g-boot.bin \
    --output output/release/tyfza1-uboot-universal.bin
sh scripts/build_flasher.sh output/release/tyfza1-flash-uboot
cp README.md COPYING VERSION output/release/
(cd output/release && sha256sum tyfza1-uboot-universal.bin tyfza1-flash-uboot README.md COPYING VERSION > SHA256SUMS)
tar --owner=0 --group=0 --numeric-owner -czf output/release/tyfza1-uboot-install.tar.gz \
    -C output/release tyfza1-uboot-universal.bin tyfza1-flash-uboot SHA256SUMS README.md COPYING VERSION
(cd output/release && sha256sum tyfza1-uboot-install.tar.gz >> SHA256SUMS)
