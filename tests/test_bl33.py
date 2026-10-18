#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the actual AArch64 BL33 wrapper in QEMU virt, without Taurus MMIO."""
import json
import lzma
from pathlib import Path
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_bl33 import build

WORK = ROOT / "build/bl33-test"


def raw_assembly(name, source, address):
    path = WORK / (name + ".S")
    path.write_text(source)
    obj, elf, raw = [WORK / (name + ext) for ext in (".o", ".elf", ".bin")]
    subprocess.run(["aarch64-linux-gnu-gcc", "-c", str(path), "-o", str(obj)], check=True)
    subprocess.run(["aarch64-linux-gnu-ld", "--build-id=none", "-Ttext", hex(address),
                    "-e", "_start", str(obj), "-o", str(elf)], check=True)
    subprocess.run(["aarch64-linux-gnu-objcopy", "-O", "binary", str(elf), str(raw)], check=True)
    return raw


class Bl33Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        cls.payload = raw_assembly("payload", """
.global _start
_start:
 ldr x4, =0x1122334455667788
 cmp x0, x4
 b.ne fail
 ldr x4, =0x8877665544332211
 cmp x1, x4
 b.ne fail
 cmp x2, #0
 b.ne fail
 ldr x4, =0x123456789abcdef0
 cmp x3, x4
 b.ne fail
 mrs x4, CurrentEL
 cmp x4, #8
 b.ne fail
 adr x1, pass_message
 ldr x2, =0x09000000
print:
 ldrb w3, [x1], #1
 cbz w3, success
 str w3, [x2]
 b print
success:
 mov x0, #0x20
 adr x1, exit_ok
 hlt #0xf000
fail:
 mov x0, #0x20
 adr x1, exit_bad
 hlt #0xf000
 b fail
.balign 8
exit_ok: .quad 0x20026, 0
exit_bad: .quad 0x20026, 2
pass_message: .asciz "BL33 PAYLOAD AND X0-X3/EL2 HANDOFF PASS\\n"
""", 0x41000000)
        # Exercise decompression of the real firmware bytes after the test entry.
        cls.plain = cls.payload.read_bytes() + (ROOT / "output/prototype/u-boot.bin").read_bytes()
        cls.payload.write_bytes(cls.plain)
        cls.wrapped = WORK / "wrapped.bin"
        cls.report = build(cls.payload, cls.wrapped, qemu=True)
        nm = subprocess.check_output(["aarch64-linux-gnu-nm", "-n", str(ROOT / "build/bl33/qemu/bl33.elf")], text=True)
        cls.symbols = {line.split()[2]: int(line.split()[0], 16) for line in nm.splitlines() if len(line.split()) == 3}
        cls.receipts = []

    @classmethod
    def tearDownClass(cls):
        (ROOT / "evidence").mkdir(exist_ok=True)
        (ROOT / "evidence/bl33-qemu.json").write_text(json.dumps({
            "scope": "Real AArch64 relocation, LZMA decoder, integrity checks and EL2 handoff on QEMU virt; no Taurus drivers or hardware tested",
            "image": cls.report, "runs": cls.receipts}, indent=2) + "\n")

    def run_qemu(self, image, address, label, alignment_check=False):
        harness = raw_assembly("harness", f"""
.global _start
_start:
 mrs x4, sctlr_el2
 orr x4, x4, #0x1000
 {'orr x4, x4, #2' if alignment_check else ''}
 msr sctlr_el2, x4
 isb
 ldr x0, =0x1122334455667788
 ldr x1, =0x8877665544332211
 mov x2, #0
 ldr x3, =0x123456789abcdef0
 ldr x15, ={address:#x}
 br x15
""", 0x42000000)
        result = subprocess.run(["qemu-system-aarch64", "-machine", "virt,virtualization=on,secure=off",
            "-cpu", "cortex-a55", "-m", "512M", "-display", "none", "-monitor", "none", "-serial", "stdio",
            "-nic", "none", "-semihosting-config", "enable=on,target=native",
            "-device", f"loader,file={image},addr={address:#x},force-raw=on",
            "-device", f"loader,file={harness},addr=0x42000000,cpu-num=0,force-raw=on"],
            text=True, capture_output=True, timeout=20)
        self.receipts.append({"case": label, "returncode": result.returncode,
                              "stdout": result.stdout, "stderr": result.stderr})
        return result

    def test_relocation_and_large_payload(self):
        result = self.run_qemu(self.wrapped, 0x44000000, "relocate-from-different-address")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BL33 PAYLOAD AND X0-X3/EL2 HANDOFF PASS", result.stdout)

    def test_relocation_with_firmware_alignment_checks(self):
        result = self.run_qemu(self.wrapped, 0x44000000, "alignment-check-enabled", True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BL33 PAYLOAD AND X0-X3/EL2 HANDOFF PASS", result.stdout)

    def test_entry_already_at_execution_address(self):
        result = self.run_qemu(self.wrapped, 0x48000000, "already-relocated")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BL33 PAYLOAD AND X0-X3/EL2 HANDOFF PASS", result.stdout)

    def test_corrupt_lzma_properties(self):
        image = bytearray(self.wrapped.read_bytes())
        image[self.symbols["payload_start"] - 0x48000000] ^= 1
        path = WORK / "bad-properties.bin"; path.write_bytes(image)
        result = self.run_qemu(path, 0x44000000, "corrupt-properties")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("integrity/decompression failed", result.stdout)
        self.assertNotIn("HANDOFF PASS", result.stdout)

    def test_corrupt_compressed_body(self):
        image = bytearray(self.wrapped.read_bytes())
        image[self.symbols["payload_start"] - 0x48000000 + 80] ^= 0x40
        path = WORK / "bad-data.bin"; path.write_bytes(image)
        result = self.run_qemu(path, 0x44000000, "corrupt-body")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("integrity/decompression failed", result.stdout)
        self.assertNotIn("HANDOFF PASS", result.stdout)

    def test_incorrect_recorded_output_size(self):
        image = bytearray(self.wrapped.read_bytes())
        start = self.symbols["payload_start"] - 0x48000000
        struct.pack_into("<Q", image, start + 5, len(self.plain) + 1)
        path = WORK / "bad-size.bin"; path.write_bytes(image)
        result = self.run_qemu(path, 0x44000000, "wrong-uncompressed-length")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("integrity/decompression failed", result.stdout)

    def test_valid_lzma_with_incorrect_output_crc(self):
        image = bytearray(self.wrapped.read_bytes())
        start = self.symbols["payload_start"] - 0x48000000
        end = self.symbols["payload_end"] - 0x48000000
        for position in range(64, 128):
            changed = bytearray(self.plain); changed[position] ^= 1
            stream = lzma.compress(changed, format=lzma.FORMAT_ALONE, filters=[{
                "id": lzma.FILTER_LZMA1, "dict_size": 1 << 20, "lc": 3, "lp": 0, "pb": 2,
                "mode": lzma.MODE_NORMAL, "nice_len": 128, "mf": lzma.MF_BT4}])
            if len(stream) == end - start:
                stream = stream[:5] + struct.pack("<Q", len(changed)) + stream[13:]
                self.assertEqual(lzma.decompress(stream, format=lzma.FORMAT_ALONE), changed)
                self.assertNotEqual(changed, self.plain)
                break
        else:
            self.fail("Unable to construct the equal-length valid LZMA corruption fixture")
        image[start:end] = stream
        path = WORK / "bad-crc.bin"; path.write_bytes(image)
        result = self.run_qemu(path, 0x44000000, "valid-stream-wrong-output-crc")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("integrity/decompression failed", result.stdout)
        self.assertNotIn("HANDOFF PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
