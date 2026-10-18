#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Verify the actual two packaged candidates and reject cryptographic/format damage."""
from pathlib import Path
import struct
import sys
import unittest
from cryptography.exceptions import InvalidSignature

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_loader import UUIDS, FIP_SIZE, FIP_OFFSETS, loader_entries, verify


def replace_entries(loader, replacements):
    entries = loader_entries(loader)
    entries.update(replacements)
    offset = 16 + (len(entries) + 1) * 40
    toc = bytearray(struct.pack("<IIQ", 0xaa640001, 0x12345678, 0))
    body = bytearray()
    for name, value in entries.items():
        toc.extend(struct.pack("<16sQQQ", bytes.fromhex(UUIDS[name]), offset, len(value), 0))
        body.extend(value)
        offset += len(value)
    fip = toc + bytes(40) + body
    assert len(fip) <= FIP_SIZE
    out = bytearray(loader)
    for start in FIP_OFFSETS:
        out[start:start + FIP_SIZE] = fip + b"\xff" * (FIP_SIZE - len(fip))
    return bytes(out)


class LoaderCryptoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.four = (ROOT / "output/candidate-4ge/taurus_spi_nand_loader.img").read_bytes()
        cls.two = (ROOT / "output/candidate-2p5g/taurus_spi_nand_loader.img").read_bytes()

    def test_both_full_candidate_chains(self):
        for data in (self.four, self.two):
            result = verify(data)
            self.assertEqual(result["certificate_signatures_verified"], 6)
            self.assertEqual(result["public_key_links_verified"], 5)
            self.assertEqual(result["payload_hashes_verified"], 3)
            self.assertEqual(result["boot_bytes"], 0x200000)

    def test_corrupt_bl33_even_when_both_fips_match(self):
        bl33 = bytearray(loader_entries(self.four)["bl33"])
        bl33[-32] ^= 1
        bad = replace_entries(self.four, {"bl33": bytes(bl33)})
        with self.assertRaisesRegex(ValueError, "Payload digest differs.*bl33"):
            verify(bad)

    def test_invalid_certificate_signature(self):
        cert = bytearray(loader_entries(self.four)["nt_cert"])
        cert[-1] ^= 1
        with self.assertRaises(InvalidSignature):
            verify(replace_entries(self.four, {"nt_cert": bytes(cert)}))

    def test_wrong_board_bl31_certificate(self):
        # The same project keys sign both variants; key linkage still passes.
        # The content certificate must nevertheless bind this exact BL31 image.
        other = loader_entries(self.two)["soc_cert"]
        with self.assertRaisesRegex(ValueError, "Payload digest differs.*bl31"):
            verify(replace_entries(self.four, {"soc_cert": other}))

    def test_changed_gpt_or_reserved_region(self):
        for address in (0x2000, 0x1f0000):
            original = bytearray(self.four); original[address] ^= 1
            with self.assertRaisesRegex(ValueError, "GPT or reserved area"):
                verify(self.four, bytes(original))

    def test_wrong_original_board_early_firmware(self):
        with self.assertRaisesRegex(ValueError, "BL2, BL31"):
            verify(self.four, self.two)

    def test_one_bad_redundant_copy(self):
        data = bytearray(self.four); data[0x100000 + 0x1a0] ^= 1
        with self.assertRaisesRegex(ValueError, "Redundant FIP payloads differ"):
            verify(data)


if __name__ == "__main__":
    unittest.main()
