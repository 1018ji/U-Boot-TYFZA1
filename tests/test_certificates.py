#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual C certificate parser on candidate and corrupted boot images."""
import ctypes as C
from pathlib import Path
import random
import subprocess
import unittest
from test_loader_crypto import replace_entries

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "overlay/board/realtek/tyfza1"
import sys
sys.path.insert(0, str(ROOT / "scripts"))
from verify_loader import loader_entries


class CertificateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work = ROOT / "build/certificate-test"; work.mkdir(parents=True, exist_ok=True)
        library = work / "certificate.so"
        subprocess.run(["cc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror",
            "-I" + str(BOARD), str(BOARD / "formats.c"), str(BOARD / "certificates.c"),
            str(ROOT / "tests/certificate_openssl.c"), "-lcrypto", "-o", str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.tyfza1_loader_certificates.argtypes = [C.c_void_p, C.c_size_t]
        cls.four = (ROOT / "output/candidate-4ge/taurus_spi_nand_loader.img").read_bytes()
        cls.two = (ROOT / "output/candidate-2p5g/taurus_spi_nand_loader.img").read_bytes()

    def parse(self, image):
        data = C.create_string_buffer(bytes(image))
        return self.lib.tyfza1_loader_certificates(data, len(image))

    def test_both_generated_candidate_chains(self):
        self.assertEqual(self.parse(self.four), 0)
        self.assertEqual(self.parse(self.two), 0)

    def test_payload_damage_with_matching_fip_copies(self):
        for name in ("bl2", "bl31", "bl33"):
            payload = bytearray(loader_entries(self.four)[name]); payload[-1] ^= 1
            self.assertNotEqual(self.parse(replace_entries(self.four, {name: payload})), 0)

    def test_each_certificate_signature(self):
        for name in ("trusted_key", "soc_key", "nt_key", "tb_cert", "soc_cert", "nt_cert"):
            cert = bytearray(loader_entries(self.four)[name]); cert[-1] ^= 1
            self.assertNotEqual(self.parse(replace_entries(self.four, {name: cert})), 0)

    def test_second_fip_certificate_damage(self):
        image = bytearray(self.four)
        import struct
        for n in range(9):
            _, offset, length, _ = struct.unpack_from("<16sQQQ", image, 0x100000 + 16+n*40)
            if n == 8:
                image[0x100000 + offset + length - 1] ^= 1
        self.assertNotEqual(self.parse(image), 0)

    def test_wrong_variant_content_certificate(self):
        other = loader_entries(self.two)["soc_cert"]
        self.assertNotEqual(self.parse(replace_entries(self.four, {"soc_cert": other})), 0)

    def test_der_length_tag_and_random_damage(self):
        original = loader_entries(self.four)["trusted_key"]
        for size in (0, 1, 2, 16, len(original)-1):
            if size:
                self.assertNotEqual(self.parse(replace_entries(self.four, {"trusted_key": original[:size]})), 0)
        for position in random.Random(9617).sample(range(len(original)), 64):
            changed = bytearray(original); changed[position] ^= 0x80
            self.assertNotEqual(self.parse(replace_entries(self.four, {"trusted_key": changed})), 0)


if __name__ == "__main__":
    unittest.main()
