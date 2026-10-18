#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare pinned U-Boot sources without modifying either upstream checkout."""
import json
from pathlib import Path
import shutil
import subprocess
import gzip
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new):
    text = path.read_text()
    if old not in text:
        raise RuntimeError(f"Source contract changed: {path}: {old!r}")
    path.write_text(text.replace(old, new))


def main():
    lock = json.loads((ROOT / "source-lock.json").read_text())
    for source in lock.values():
        path = ROOT / "sources" / source["directory"]
        actual = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
        if actual != source["commit"]:
            raise RuntimeError(f"Wrong source revision: {path}: {actual}")
    dest = ROOT / "build/u-boot"
    fresh = not dest.exists()
    if not fresh:
        if json.loads((dest / ".tyfza1-sources.json").read_text()) != lock:
            raise RuntimeError("Prepared source revision differs from source-lock.json")
    else:
        dest.mkdir(parents=True)
        reference = ROOT / "sources" / lock["reference"]["directory"]
        proc = subprocess.Popen(["git", "-C", str(reference), "archive", lock["reference"]["commit"]], stdout=subprocess.PIPE)
        with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
            archive.extractall(dest, filter="data")
        if proc.wait():
            raise RuntimeError("git archive failed")
    vendor = ROOT / "sources" / lock["realtek"]["directory"] / lock["realtek"]["subdirectory"]
    common = vendor / "board/realtek_10G_PON/common"
    board = dest / "board/realtek/tyfza1"
    for name in ["eth_ni.c", "eth_ni.h", "eth_ni_taurus.c"]:
        out = board / "vendor" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(common / name, out)
    shutil.copy2(vendor / "drivers/gpio/cortina_gpio.c", board / "vendor/gpio.c")
    for name in ["cortina_spi_nand.c", "cortina_spi_nand.h", "cortina_spi_nand_base.c", "spi-nand-core.c"]:
        out = board / "vendor/spi_nand" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(common / "spi_nand" / name, out)
    regs = dest / "arch/arm/include/asm/arch-taurus/registers.h"
    regs.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(vendor / "arch/arm/include/asm/arch-taurus/registers.h", regs)
    # U-Boot removed common.h; include the actual interfaces in imported code.
    compat = "#include <config.h>\n#include <dm.h>\n#include <env.h>\n#include <init.h>\n#include <stdio.h>\n#include <vsprintf.h>\n#include <linux/types.h>\n#include <linux/kernel.h>\n#include <asm/arch/registers.h>"
    for path in (board / "vendor").rglob("*.c"):
        replace(path, "#include <common.h>", compat)
        text = path.read_text()
        if text.count("#include <dm.h>") > 1:
            path.write_text(text.replace("#include <dm.h>", "", 1))
    replace(board / "vendor/eth_ni.c", "static struct phy_driver ni_internal =", "U_BOOT_PHY_DRIVER(tyfza1_internal) =")
    replace(board / "vendor/eth_ni.c", "\tphy_register(&ni_internal);", "")
    replace(board / "vendor/eth_ni.c", "cmdtp->help", "cmdtp->usage")
    replace(board / "vendor/eth_ni.c", "//ni_enable_tx_rx(priv->active_port, 0);", "if (is_valid_port(priv, priv->active_port))\n\t\tni_enable_tx_rx(priv->active_port, 0);")
    replace(board / "vendor/eth_ni.c", '\t/*\n\tif ((buf = env_get("auto_scan_active_port")) != 0) {\n\t\tactive_scan = simple_strtoul(buf, NULL, 0);\n\t\tprintf(MODULE_NAME": env active_scan=%d\\n", active_scan);\n\t\tpriv->active_scan = active_scan;\n\t}\n\t*/', '\tif ((buf = env_get("auto_scan_active_port")) != 0) {\n\t\tactive_scan = simple_strtoul(buf, NULL, 0);\n\t\tpriv->active_scan = !!active_scan;\n\t}')
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c", "#include <watchdog.h>", "#include <u-boot/schedule.h>")
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c", "WATCHDOG_RESET();", "schedule();")
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c", "(corrected >= (info->ecc_strength-2))", "(*corrected >= (info->ecc_strength-2))")
    replace(board / "vendor/spi_nand/cortina_spi_nand_base.c", "int timeout = start + CONFIG_SYS_HZ;", "int timeout = CONFIG_SYS_HZ;")
    replace(board / "vendor/spi_nand/spi-nand-core.c", "#include <nand.h>", "#include <nand.h>\n#include <linux/mtd/rawnand.h>")
    shutil.copytree(ROOT / "overlay", dest, dirs_exist_ok=True)
    # Preserve the complete frontend while reducing the two-FIP flash footprint.
    http = dest / "net/lwip/httpd.c"
    shutil.copy2(reference_path := ROOT / "sources" / lock["reference"]["directory"] / "net/lwip/httpd.c", http)
    page = dest / "net/lwip/httpd-page.html"
    page_source = ROOT / "overlay/net/lwip/httpd-page.html"
    raw = page_source.read_bytes() if page_source.exists() else reference_path.with_name("httpd-page.html").read_bytes()
    compressed = gzip.compress(raw, mtime=0)
    page.write_bytes(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Encoding: gzip\r\nConnection: close\r\nContent-Length: " + str(len(compressed)).encode() + b"\r\n\r\n" + compressed)
    replace(http, "fs_set_data(file, httpd_page, httpd_page_size);", "fs_set_data(file, httpd_page, httpd_page_size);\n\t\tfile->flags = FS_FILE_FLAGS_HEADER_INCLUDED;")
    replace(http, '#include <net/httpd.h>', '#include <net/httpd.h>\n#include <tyfza1_recovery.h>')
    replace(http, '#define HTTPD_UBI_PART\t\t"ubi"', '#define HTTPD_UBI_PART\t\t"ubi_device"')
    replace(http, '"airoha,an758x-recovery-layout"', '"tianyi,tyfza1-recovery-layout"')
    replace(http, "static int run_bootloader_update(bool bl2)\n{", "static int run_bootloader_update(bool bl2)\n{\n\tif (IS_ENABLED(CONFIG_TARGET_TYFZA1))\n\t\treturn tyfza1_install_loader(buffer_addr, buffer_size, bl2, service_network);")
    replace(http, "static int run_firmware_update(void)\n{", "static int run_firmware_update(void)\n{\n\tif (IS_ENABLED(CONFIG_TARGET_TYFZA1))\n\t\treturn tyfza1_install_system(buffer_addr, buffer_size, service_network);")
    replace(http, "static int run_ubi_rebuild(void)\n{", "static int run_ubi_rebuild(void)\n{\n\tif (IS_ENABLED(CONFIG_TARGET_TYFZA1))\n\t\treturn tyfza1_rebuild_ubi(service_network);")
    if fresh:
        arm = dest / "arch/arm/Kconfig"
        replace(arm, "config TARGET_PRESIDIO_ASIC", "config TARGET_TYFZA1\n\tbool \"Tianyi TYFZA1 (RTL9617CVW)\"\n\tselect ARM64\n\tselect DM\n\tselect OF_CONTROL\n\tselect BOARD_LATE_INIT\n\nconfig TARGET_PRESIDIO_ASIC")
        with arm.open("a") as out:
            out.write('\nsource "board/realtek/tyfza1/Kconfig"\n')
        replace(dest / "drivers/serial/Kconfig", "depends on DM_SERIAL && TARGET_PRESIDIO_ASIC", "depends on DM_SERIAL && (TARGET_PRESIDIO_ASIC || TARGET_TYFZA1)")
    (dest / ".tyfza1-sources.json").write_text(json.dumps(lock, indent=2) + "\n")
    print(dest)


if __name__ == "__main__":
    main()
