#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual C upload parsers, including malformed NAND/FIP/tar inputs."""
import ctypes as C
import io
from pathlib import Path
import random
import struct
import subprocess
import tarfile
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "overlay/board/realtek/tyfza1"
IDS = [bytes.fromhex(x) for x in (
    "5ff9ec0b4d223e4da544c39d81c73f0a", "47d4086d4cfe98469b952950cbbd5a00",
    "d6d0eea7fcead54b97829934f234b6e4")]


class Payload(C.Structure):
    _fields_ = [("data", C.c_void_p), ("size", C.c_size_t)]


class Fip(C.Structure):
    _fields_ = [(x, Payload) for x in ("bl2", "bl31", "bl33")]


class Firmware(C.Structure):
    _fields_ = [(x, Payload) for x in ("kernel", "root")]


def fip():
    buf = bytearray(struct.pack("<IIQ", 0xaa640001, 0x12345678, 0))
    payload = b"BL2 payload" + b"BL31 payload" + b"UBoot payload"
    off = 16 + 4 * 40
    for uid, length in zip(IDS, (11, 12, 13)):
        buf.extend(struct.pack("<16sQQQ", uid, off, length, 0))
        off += length
    return buf + bytes(40) + payload


def loader():
    # Use the real GPT geometry and checksums rather than magic bytes alone.
    buf = bytearray((ROOT / 'evidence/stock-boot/4ge-boot.bin').read_bytes())
    fw = fip()
    for pos in (0x40000, 0x100000):
        buf[pos:pos + 0xc0000] = fw + b'\xff' * (0xc0000 - len(fw))
    return buf


def update_gpt_crcs(buf, header, entries):
    struct.pack_into('<I', buf, header + 0x58, zlib.crc32(buf[entries:entries + 0x4000]))
    struct.pack_into('<I', buf, header + 0x10, 0)
    struct.pack_into('<I', buf, header + 0x10, zlib.crc32(buf[header:header + 92]))


def sysupgrade(board="tianyi_tyfza1", extra=()):
    stream = io.BytesIO()
    root = bytearray(128)
    root[:4] = b"hsqs"
    struct.pack_into("<Q", root, 40, len(root))
    kernel = b"\xd0\x0d\xfe\xed" + bytes(128)
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        directory = "sysupgrade-" + board + "/"
        for name, data in [(directory + "CONTROL", b"BOARD=" + board.encode()),
                           (directory + "kernel", kernel), (directory + "root", root), *extra]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return bytearray(stream.getvalue())


class FormatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        library = Path(cls.tmp.name) / "formats.so"
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-shared", "-fPIC",
                        str(SRC / "formats.c"), "-o", str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        for name, typ in [("fip", Fip), ("loader", Fip), ("sysupgrade", Firmware)]:
            fn = getattr(cls.lib, "tyf_parse_" + name)
            fn.argtypes = [C.c_void_p, C.c_size_t, C.POINTER(typ)]
            fn.restype = C.c_int
        cls.lib.tyf_loader_preserves_device.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t]
        cls.lib.tyf_loader_preserves_device.restype = C.c_int
        cls.lib.tyf_select_loader.argtypes = [C.c_void_p, C.c_size_t, C.c_char_p, C.POINTER(Payload)]
        cls.lib.tyf_select_loader.restype = C.c_int

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def parse(self, name, data):
        buf = C.create_string_buffer(bytes(data))
        out = Firmware() if name == "sysupgrade" else Fip()
        return getattr(self.lib, "tyf_parse_" + name)(buf, len(data), C.byref(out)), out

    def test_fip_payloads(self):
        ret, parsed = self.parse("fip", fip())
        self.assertEqual(ret, 0)
        self.assertEqual([parsed.bl2.size, parsed.bl31.size, parsed.bl33.size], [11, 12, 13])

    def test_fip_bounds_and_overlaps(self):
        for offset, length in [(0, 4), (16, 4), (2**64 - 1, 4), (180, 2**64 - 1), (176, 20)]:
            buf = fip()
            struct.pack_into("<QQ", buf, 56 + 16, offset, length)
            self.assertNotEqual(self.parse("fip", buf)[0], 0)

    def test_fip_duplicate_and_missing_ids(self):
        buf = fip(); buf[56:72] = IDS[0]
        self.assertNotEqual(self.parse("fip", buf)[0], 0)
        buf = fip(); buf[56:72] = bytes(16)
        self.assertNotEqual(self.parse("fip", buf)[0], 0)

    def test_loader_redundancy(self):
        buf = loader()
        self.assertEqual(self.parse("loader", buf)[0], 0)
        buf[0x100000 + len(fip()) - 1] ^= 1
        self.assertNotEqual(self.parse("loader", buf)[0], 0)

    def test_loader_geometry(self):
        for size in (0, 512, 0x1fffff, 0x200001):
            self.assertNotEqual(self.parse("loader", bytes(size))[0], 0)

    def select(self, data, variant):
        buf = C.create_string_buffer(bytes(data))
        selected = Payload()
        ret = self.lib.tyf_select_loader(buf, len(data), variant.encode(), C.byref(selected))
        return ret, C.string_at(selected.data, selected.size) if ret == 0 else b''

    def test_universal_board_selection(self):
        first, second = loader(), loader()
        for offset in (0x40000, 0x100000):
            second[offset + len(fip()) - 1] ^= 0x12
        bundle = b'TYFZA1-UBOOT-V1\0' + first + second
        self.assertEqual(self.select(bundle, '4ge'), (0, bytes(first)))
        self.assertEqual(self.select(bundle, '2p5g'), (0, bytes(second)))
        self.assertNotEqual(self.select(bundle, 'unknown')[0], 0)
        self.assertEqual(self.select(first, '4ge'), (0, bytes(first)))

    def test_universal_rejects_corrupt_header_or_either_image(self):
        bundle = bytearray(b'TYFZA1-UBOOT-V1\0') + loader() + loader()
        for offset in (0, 16 + 512, 16 + 0x200000 + 512):
            damaged = bundle.copy(); damaged[offset] ^= 1
            for variant in ('4ge', '2p5g'):
                self.assertNotEqual(self.select(damaged, variant)[0], 0)
        self.assertNotEqual(self.select(bundle[:-1], '4ge')[0], 0)

    def preserves(self, next_image, current):
        a, b = C.create_string_buffer(bytes(next_image)), C.create_string_buffer(bytes(current))
        return self.lib.tyf_loader_preserves_device(a, len(next_image), b, len(current))

    def test_repair_different_bl33_copies(self):
        next_image, current = loader(), loader()
        current[0x100000 + len(fip()) - 1] ^= 1
        self.assertEqual(self.preserves(next_image, current), 0)

    def test_repair_one_corrupt_copy(self):
        for off in (0x40000, 0x100000):
            current = loader(); current[off] ^= 1
            self.assertEqual(self.preserves(loader(), current), 0)
            current = loader(); current[off + 176] ^= 1
            self.assertEqual(self.preserves(loader(), current), 0)

    def test_reject_no_matching_early_firmware(self):
        current = loader()
        for off in (0x40000, 0x100000): current[off + 176] ^= 1
        self.assertNotEqual(self.preserves(loader(), current), 0)

    def test_reject_modified_boot_layout(self):
        for off in (0x1000, 0x1d0000):
            current = loader(); current[off] ^= 1
            self.assertNotEqual(self.preserves(loader(), current), 0)

    def test_accept_per_device_gpt_identity(self):
        current = loader()
        for header, entries in ((0x200, 0x400), (0x200000 - 0x200, 0x200000 - 0x4200)):
            for off in (header + 0x38, header + 0x47,
                        entries + 0x10, entries + 0x80 + 0x1f):
                current[off] ^= 1
            update_gpt_crcs(current, header, entries)
        self.assertEqual(self.preserves(loader(), current), 0)

    def test_reject_invalid_gpt_crcs_in_current_or_candidate(self):
        for header, entries in ((0x200, 0x400), (0x1ffe00, 0x1fbe00)):
            for damage in ('header_crc', 'table_crc', 'disk_guid', 'partition_guid'):
                bad = loader()
                if damage == 'header_crc':
                    bad[header + 0x10] ^= 1
                elif damage == 'table_crc':
                    bad[header + 0x58] ^= 1
                    struct.pack_into('<I', bad, header + 0x10, 0)
                    struct.pack_into('<I', bad, header + 0x10, zlib.crc32(bad[header:header + 92]))
                else:
                    bad[header + 0x38 if damage == 'disk_guid' else entries + 0x10] ^= 1
                for candidate, current in ((loader(), bad), (bad, loader())):
                    with self.subTest(header=header, damage=damage):
                        self.assertNotEqual(self.preserves(candidate, current), 0)

    def test_reject_unsupported_gpt_geometry(self):
        for off, value in ((12, 0), (12, 513), (72, 0xffffffff), (80, 129), (84, 256)):
            bad = loader()
            struct.pack_into('<I', bad, 0x200 + off, value)
            update_gpt_crcs(bad, 0x200, 0x400)
            self.assertNotEqual(self.preserves(bad, bad), 0)

    def test_accept_both_real_board_gpts_and_per_device_guids(self):
        for variant in ('4ge', '2p5g'):
            candidate = (ROOT / f'evidence/stock-boot/{variant}-boot.bin').read_bytes()
            current = bytearray(candidate)
            self.assertEqual(self.preserves(candidate, current), 0)
            for header, entries in ((0x200, 0x400), (0x1ffe00, 0x1fbe00)):
                current[header + 0x38:header + 0x48] = bytes(range(16))
                for index in (0, 1):
                    start = entries + index * 128 + 0x10
                    current[start:start + 16] = bytes([index + 71]) * 16
                update_gpt_crcs(current, header, entries)
            self.assertEqual(self.preserves(candidate, current), 0)

    def test_accept_stock_fip_lengths_from_reported_4ge_boot(self):
        candidate = loader()
        current = bytearray(candidate)
        # V1.0.5 report: identical BL2/BL31, shorter OEM BL33 and GPT FIP lengths.
        for header, entries in ((0x200, 0x400), (0x1ffe00, 0x1fbe00)):
            for index, last in enumerate((0x79e, 0xd9e)):
                struct.pack_into('<Q', current, entries + index * 128 + 0x28, last)
            update_gpt_crcs(current, header, entries)
        self.assertEqual(self.preserves(candidate, current), 0)

    def test_reject_fip_gpt_lengths_outside_slots_or_too_short(self):
        candidate = (ROOT / 'evidence/stock-boot/4ge-boot.bin').read_bytes()
        for index, start in enumerate((0x200, 0x800)):
            for last in (start - 1, start, start + 0x600, 2**64 - 1):
                bad = bytearray(candidate)
                for header, entries in ((0x200, 0x400), (0x1ffe00, 0x1fbe00)):
                    struct.pack_into('<Q', bad, entries + index * 128 + 0x28, last)
                    update_gpt_crcs(bad, header, entries)
                with self.subTest(index=index, last=last):
                    self.assertNotEqual(self.preserves(candidate, bad), 0)
                    self.assertNotEqual(self.preserves(bad, bad), 0)

    def test_reject_different_primary_and_backup_fip_lengths(self):
        current = loader()
        struct.pack_into('<Q', current, 0x400 + 0x28, 0x79e)
        update_gpt_crcs(current, 0x200, 0x400)
        self.assertNotEqual(self.preserves(loader(), current), 0)

    def test_fip_gpt_capacity_includes_last_payload_and_sector_rounding(self):
        candidate = (ROOT / 'evidence/stock-boot/4ge-boot.bin').read_bytes()
        used = 0
        for pos in range(0x40000 + 16, 0x40000 + 16 + 32 * 40, 40):
            uid, offset, length, _ = struct.unpack_from('<16sQQQ', candidate, pos)
            if uid == bytes(16): break
            used = max(used, offset + length)
        for shorten, expected in ((0, 0), (1, -1)):
            current = bytearray(candidate)
            for header, entries in ((0x200, 0x400), (0x1ffe00, 0x1fbe00)):
                for index, first in enumerate((0x200, 0x800)):
                    last = first + (used + 511) // 512 - 1 - shorten
                    struct.pack_into('<Q', current, entries + index * 128 + 0x28, last)
                update_gpt_crcs(current, header, entries)
            with self.subTest(shorten=shorten):
                self.assertEqual(self.preserves(candidate, current), expected)

    def test_reject_modified_gpt_layout(self):
        for header, entries in ((0x200, 0x400), (0x200000 - 0x200, 0x200000 - 0x4200)):
            for off in (header + 0x20, header + 0x48, entries, entries + 0x20,
                        entries + 0x30, entries + 0x38, entries + 2 * 128 + 0x28):
                current = loader(); current[off] ^= 1
                update_gpt_crcs(current, header, entries)
                self.assertNotEqual(self.preserves(loader(), current), 0)

    def test_both_board_archives(self):
        for board in ("tianyi_tyfza1", "tianyi_tyfza1-2p5g"):
            self.assertEqual(self.parse("sysupgrade", sysupgrade(board))[0], 0)

    def test_reject_foreign_board_and_duplicate_kernel(self):
        self.assertNotEqual(self.parse("sysupgrade", sysupgrade("airoha_an7581"))[0], 0)
        self.assertNotEqual(self.parse("sysupgrade", sysupgrade(extra=[("sysupgrade-tianyi_tyfza1/kernel", b"bad")]))[0], 0)

    def test_tar_checksum_and_truncation(self):
        buf = sysupgrade(); buf[0] ^= 1
        self.assertNotEqual(self.parse("sysupgrade", buf)[0], 0)
        for length in (0, 1, 511, 512, 1024, 2049):
            self.assertNotEqual(self.parse("sysupgrade", sysupgrade()[:length])[0], 0)

    def test_symlink_rejected(self):
        buf = sysupgrade()
        buf[1024 + 156] = ord("2")
        buf[1024 + 148:1024 + 156] = b"        "
        checksum = sum(buf[1024:1536])
        buf[1024 + 148:1024 + 156] = (f"{checksum:06o}\0 ").encode()
        self.assertNotEqual(self.parse("sysupgrade", buf)[0], 0)

    def test_small_random_inputs(self):
        rng = random.Random(9617)
        for _ in range(1000):
            buf = rng.randbytes(rng.randrange(512))
            self.assertNotEqual(self.parse("fip", buf)[0], 0)
            self.assertNotEqual(self.parse("sysupgrade", buf)[0], 0)


if __name__ == "__main__":
    unittest.main()
