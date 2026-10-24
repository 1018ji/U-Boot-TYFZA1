#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check the pinned rescue package, legacy script envelope and protected layout."""
import hashlib
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_ttl_recovery as ttl


class TtlRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = (ROOT / 'output/release/tyfza1-uboot-universal.bin').read_bytes()

    def prepare_fixture(self, data):
        # CI signs its own build. The public CLI still pins official v1.4.
        with patch.object(ttl, 'BUNDLE_SHA256', hashlib.sha256(data).hexdigest()):
            return ttl.prepare(data)

    def test_reject_untrusted_package_or_linux_installer(self):
        for data in (b'#!/bin/sh\ninstaller', self.bundle[:-1], self.bundle[16:16 + ttl.BOOT]):
            with self.assertRaises(ValueError):
                ttl.prepare(data)
        damaged = bytearray(self.bundle); damaged[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            ttl.prepare(damaged)

    def test_legacy_header_and_data_crcs_cover_the_complete_file(self):
        data = self.prepare_fixture(self.bundle)
        fields = struct.unpack('>7I4B32s', data[:64])
        header = bytearray(data[:64]); header[4:8] = bytes(4)
        self.assertEqual(fields[0], 0x27051956)
        self.assertEqual(fields[1], zlib.crc32(header))
        self.assertEqual(fields[3], len(data) - 64)
        self.assertEqual(fields[6], zlib.crc32(data[64:]))
        self.assertEqual(fields[9], 6)
        size, terminator = struct.unpack_from('>II', data, 64)
        self.assertEqual(terminator, 0)
        script = data[72:72 + size].decode('ascii')
        self.assertIn('TTL CHECK OK', script)
        self.assertIn('TTL WRITE OK', script)
        self.assertEqual(data[ttl.PAYLOAD:], self.bundle)
        self.assertLess(72 + size, ttl.PAYLOAD)

    def test_layout_mask_still_covers_starts_attributes_and_reserved_bytes(self):
        ranges = list(ttl.fixed_layout_ranges())
        covered = lambda off: any(start <= off < start + size for start, size in ranges)
        for off in (0, 0x220, 0x250, 0x400, 0x420, 0x430, 0x10000, 0x1d0000):
            self.assertTrue(covered(off), hex(off))
        for off in (0x210, 0x238, 0x258, 0x410, 0x428, 0x1fbe10, 0x1fbe28, 0x1ffe10):
            self.assertFalse(covered(off), hex(off))
        self.assertFalse(covered(0x40000))
        self.assertFalse(covered(0x100000))


if __name__ == '__main__':
    unittest.main()
