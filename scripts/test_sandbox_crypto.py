#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the real U-Boot DER, RSA, PSS and SHA implementation in U-Boot sandbox."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import struct
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_loader_crypto import replace_entries
from verify_loader import loader_entries
import prepare_ttl_recovery as ttl

source = ROOT / "build/u-boot"
testlib = source / "lib/tyfza1-cert-test"
testlib.mkdir(exist_ok=True)
for name in ("formats.h", "formats.c", "certificates.h", "certificates.c", "certificate-crypto.c"):
    shutil.copy2(ROOT / "overlay/board/realtek/tyfza1" / name, testlib / name)
shutil.copy2(ROOT / "tests/sandbox_cert_command.c", testlib / "test-command.c")
shutil.copy2(ROOT / "tests/sandbox_ttl_command.c", testlib / "ttl-command.c")
(testlib / "Makefile").write_text("obj-y += formats.o certificates.o certificate-crypto.o test-command.o ttl-command.o\n")
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

# Exercise the exact generated legacy image with real source/Hush/hash/memory
# commands. Only NAND I/O is replaced by the bounded host-side fixture.
bundle = (ROOT / "output/release/tyfza1-uboot-universal.bin").read_bytes()
with patch.object(ttl, 'BUNDLE_SHA256', hashlib.sha256(bundle).hexdigest()):
    rescue = ttl.prepare(bundle)
four = (ROOT / 'evidence/stock-boot/4ge-boot.bin').read_bytes()
two = (ROOT / 'evidence/stock-boot/2p5g-boot.bin').read_bytes()
cases = [
    ('check-only', four, rescue, 'check', 0, 'unchanged', 0, 'TTL CHECK OK'),
    ('install-4ge', four, rescue, 'write', 0, 'installed', 2, 'TTL WRITE OK'),
    ('install-2p5g', two, rescue, 'write', 0, 'installed', 2, 'TTL WRITE OK'),
]


def update_gpt_crcs(data, header, table):
    struct.pack_into('<I', data, header + 88, zlib.crc32(data[table:table + 0x4000]))
    struct.pack_into('<I', data, header + 16, 0)
    struct.pack_into('<I', data, header + 16, zlib.crc32(data[header:header + 92]))


identity = bytearray(four)
for h, e in ((0x200, 0x400), (0x1ffe00, 0x1fbe00)):
    identity[h + 56:h + 72] = bytes(range(16))
    identity[e + 16:e + 32] = b'\x42' * 16
    for i, last in enumerate((0x79e, 0xd9e)):
        struct.pack_into('<Q', identity, e + i * 128 + 40, last)
    update_gpt_crcs(identity, h, e)
cases.append(('per-device-gpt', bytes(identity), rescue, 'write', 0, 'installed', 2, 'TTL WRITE OK'))
for label, offset in (('bad-gpt-crc', 0x210), ('reserved-change', 0x1d0000)):
    damaged = bytearray(four); damaged[offset] ^= 1
    cases.append((label, bytes(damaged), rescue, 'write', 0, 'unchanged', 0, 'TTL STOP'))
foreign = bytearray(four)
for at in (0x40000, 0x100000): foreign[at + 0x1a0] ^= 1
cases.append(('foreign-early-firmware', bytes(foreign), rescue, 'write', 0, 'unchanged', 0, 'TTL STOP'))
bad_table = bytearray(four); bad_table[0x410] ^= 1
cases.append(('bad-table-crc', bytes(bad_table), rescue, 'write', 0, 'unchanged', 0, 'TTL STOP'))
capacity = bytearray(four)
for h, e in ((0x200, 0x400), (0x1ffe00, 0x1fbe00)):
    struct.pack_into('<Q', capacity, e + 40, 0x800)
    update_gpt_crcs(capacity, h, e)
cases.append(('bad-fip-capacity', bytes(capacity), rescue, 'write', 0, 'unchanged', 0, 'TTL STOP'))
split = bytearray(four)
struct.pack_into('<Q', split, 0x428, 0x79e)
update_gpt_crcs(split, 0x200, 0x400)
cases.append(('split-gpt-lengths', bytes(split), rescue, 'write', 0, 'unchanged', 0, 'TTL STOP'))
for fault, label, state, erased in ((1, 'bad-block', 'unchanged', 0),
                                    (2, 'erase-failure', 'unchanged', 0),
                                    (3, 'write-failure', 'primary', 1),
                                    (4, 'readback-failure', 'primary', 1)):
    cases.append((label, four, rescue, 'write', fault, state, erased, 'TTL STOP'))
corrupt = bytearray(rescue); corrupt[ttl.PAYLOAD + 512] ^= 1
cases.append(('bad-script-crc', four, bytes(corrupt), 'write', 0, 'unchanged', 0, 'Bad data crc'))
# Keep the outer CRCs valid to ensure the embedded SHA256 gate is exercised.
struct.pack_into('>I', corrupt, 24, zlib.crc32(corrupt[64:]))
struct.pack_into('>I', corrupt, 4, 0)
struct.pack_into('>I', corrupt, 4, zlib.crc32(corrupt[:64]))
cases.append(('wrong-embedded-package', four, bytes(corrupt), 'write', 0, 'unchanged', 0, 'TTL STOP'))
ttl_rows = []
for label, boot, script, action, fault, state, erased, message in cases:
    old_path = ROOT / f'build/sandbox-cert/ttl-{label}-boot.bin'
    script_path = ROOT / f'build/sandbox-cert/ttl-{label}.scr'
    old_path.write_bytes(boot); script_path.write_bytes(script)
    command = (f'host load hostfs - 10000000 {old_path}; ttlfixture 10000000 {fault:x}; '
               f'host load hostfs - 11000000 {script_path}; setenv verify yes; '
               f'setenv ttl_action {action}; source 11000000; ttlassert {state} {erased:x}')
    result = subprocess.run([str(binary), '-d', str(dtb), '-c', command],
                            text=True, capture_output=True, timeout=45)
    if message not in result.stdout or 'TTL ASSERT OK' not in result.stdout or 'TTL ASSERT FAILED' in result.stdout:
        raise RuntimeError(label + '\n' + result.stdout + result.stderr)
    ttl_rows.append({'case': label, 'result': 'passed', 'expected_erases': erased})
(ROOT / 'evidence/ttl-recovery-sandbox.json').write_text(json.dumps({
    'scope': 'Generated recovery image executed by real U-Boot source/Hush/hash/memory commands; NAND calls modeled, no physical Flash writes',
    'cases': ttl_rows,
}, indent=2) + '\n')
print(json.dumps({'ttl_recovery_cases': len(ttl_rows), 'result': 'passed'}))
