#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the real U-Boot DER, RSA, PSS and SHA implementation in U-Boot sandbox."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_loader_crypto import replace_entries
from verify_loader import loader_entries

source = ROOT / "build/u-boot"
testlib = source / "lib/tyfza1-cert-test"
testlib.mkdir(exist_ok=True)
for name in ("formats.h", "formats.c", "certificates.h", "certificates.c", "certificate-crypto.c"):
    shutil.copy2(ROOT / "overlay/board/realtek/tyfza1" / name, testlib / name)
shutil.copy2(ROOT / "tests/sandbox_cert_command.c", testlib / "test-command.c")
(testlib / "Makefile").write_text("obj-y += formats.o certificates.o certificate-crypto.o test-command.o\n")
makefile = source / "lib/Makefile"
line = "obj-$(CONFIG_SANDBOX) += tyfza1-cert-test/\n"
if line not in makefile.read_text():
    with makefile.open("a") as out:
        out.write("\n" + line)
shutil.copy2(ROOT / "tests/sandbox_cert_defconfig", source / "configs/sandbox_tyfza1_cert_defconfig")
shutil.copy2(ROOT / "tests/sandbox-tyfza1-test.dts", source / "arch/sandbox/dts/sandbox-tyfza1-test.dts")
subprocess.run(["make", "-C", str(source), "O=../sandbox-cert", "sandbox_tyfza1_cert_defconfig"], check=True)
subprocess.run(["make", "-C", str(source), "O=../sandbox-cert", "-j6"], check=True)
binary = ROOT / "build/sandbox-cert/u-boot"
dtb = ROOT / "build/sandbox-cert/u-boot.dtb"
rows = []
inputs = []
for variant in ("4ge", "2p5g"):
    path = ROOT / f"output/candidate-{variant}/taurus_spi_nand_loader.img"
    inputs.append((variant, path, True))
image = inputs[0][1].read_bytes()
for name in ("bl33", "nt_cert"):
    damaged = bytearray(loader_entries(image)[name]); damaged[-1] ^= 1
    path = ROOT / f"build/sandbox-cert/bad-{name}.bin"
    path.write_bytes(replace_entries(image, {name: bytes(damaged)}))
    inputs.append(("corrupt-" + name, path, False))
for label, path, valid in inputs:
    command = f"host load hostfs - 1000000 {path}; tyfcert 1000000 200000"
    result = subprocess.run([str(binary), "-d", str(dtb), "-c", command],
                            text=True, capture_output=True, timeout=30)
    if ("TYF CERT OK (0)" if valid else "TYF CERT REJECT") not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    rows.append({"case": label, "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
report = {"scope": "Actual U-Boot sandbox executable uses production certificate parser, U-Boot RSA public-key parser/software exponentiation/PSS and SHA256; no Taurus NAND tested", "runs": rows}
(ROOT / "evidence/uboot-sandbox-crypto.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"cases": len(rows), "result": "passed"}))
