#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check Taurus FIP boundaries, payload identity and the complete embedded TBBR chain."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ObjectIdentifier

BOOT_SIZE, FIP_SIZE, FIP_OFFSETS = 0x200000, 0xc0000, (0x40000, 0x100000)
UUIDS = {
    "bl2": "5ff9ec0b4d223e4da544c39d81c73f0a", "bl31": "47d4086d4cfe98469b952950cbbd5a00",
    "bl33": "d6d0eea7fcead54b97829934f234b6e4", "trusted_key": "827ee890f860e411a1b4777a21b4f94c",
    "soc_key": "8ab8beccf960e4119ad0eb4822d8dcf8", "nt_key": "8ad5832afb60e4118aafdf30bbc49859",
    "tb_cert": "d6e269ea5d63e4118d8c9fbabe9956a5", "soc_cert": "e2b20c205e63e4119ce8abccf92bb666",
    "nt_cert": "8ec4c1f35d63e411a7a987ee40b23fa7",
}
OID_BASE = "1.3.6.1.4.1.4128.2100."
CUSTOM_EXTENSIONS = {
    "trusted_key": {1, 302, 303}, "soc_key": {1, 501}, "nt_key": {2, 1101},
    "tb_cert": {1, 201, 202, 203}, "soc_cert": {1, 603}, "nt_cert": {2, 1201},
}


def fip_entries(data):
    if len(data) < 56 or struct.unpack_from("<I", data)[0] != 0xaa640001:
        raise ValueError("Invalid FIP header")
    raw = []
    for pos in range(16, min(len(data) - 39, 16 + 32 * 40), 40):
        uid, offset, size, flags = struct.unpack_from("<16sQQQ", data, pos)
        if uid == bytes(16):
            toc_end = pos + 40
            break
        raw.append((uid.hex(), offset, size, flags))
    else:
        raise ValueError("FIP has no bounded ToC terminator")
    entries = {}
    for uid, offset, size, flags in raw:
        if uid in entries or not size or offset < toc_end or offset > len(data) or size > len(data) - offset:
            raise ValueError("Invalid, duplicated or truncated FIP entry")
        if any(offset < old[1] + old[2] and old[1] < offset + size for old in raw if old[0] != uid):
            raise ValueError("Overlapping FIP payloads")
        entries[uid] = data[offset:offset + size]
    if set(entries) != set(UUIDS.values()):
        raise ValueError("Expected precisely BL2, BL31, BL33 and the six Taurus certificates")
    return {name: entries[uid] for name, uid in UUIDS.items()}


def loader_entries(data):
    if len(data) != BOOT_SIZE or data[512:520] != b"EFI PART" or data[-512:-504] != b"EFI PART":
        raise ValueError("Expected the original 2 MiB ECC-data boot layout")
    first, second = [fip_entries(data[pos:pos + FIP_SIZE]) for pos in FIP_OFFSETS]
    if first != second:
        raise ValueError("Redundant FIP payloads differ")
    return first


def pub_der(key):
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def extension(cert, number):
    return cert.extensions.get_extension_for_oid(ObjectIdentifier(OID_BASE + str(number))).value.value


def verify_chain(entries):
    certs = {name: x509.load_der_x509_certificate(entries[name]) for name in CUSTOM_EXTENSIONS}
    for name, cert in certs.items():
        key = cert.public_key()
        if not isinstance(key, rsa.RSAPublicKey) or key.key_size != 2048 or cert.signature_hash_algorithm.name != "sha256" or \
                cert.signature_algorithm_oid.dotted_string != "1.2.840.113549.1.1.10":
            raise ValueError(f"Unexpected signing profile: {name}")
        key.verify(cert.signature, cert.tbs_certificate_bytes,
                   padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
        actual = {int(e.oid.dotted_string[len(OID_BASE):]) for e in cert.extensions if e.oid.dotted_string.startswith(OID_BASE)}
        if actual != CUSTOM_EXTENSIONS[name]:
            raise ValueError(f"Unexpected critical TBBR extension set: {name}")
        if any(not e.critical for e in cert.extensions if e.oid.dotted_string.startswith(OID_BASE)):
            raise ValueError(f"TBBR extensions must be critical: {name}")
    relationships = [("trusted_key", 302, "soc_key"), ("trusted_key", 303, "nt_key"),
                     ("soc_key", 501, "soc_cert"), ("nt_key", 1101, "nt_cert")]
    for parent, oid, child in relationships:
        if extension(certs[parent], oid) != pub_der(certs[child].public_key()):
            raise ValueError(f"Certificate public-key link differs: {parent} -> {child}")
    if pub_der(certs["trusted_key"].public_key()) != pub_der(certs["tb_cert"].public_key()):
        raise ValueError("BL2 and trusted-key certificates have different root keys")
    digest_prefix = bytes.fromhex("3031300d060960864801650304020105000420")
    for cert, oid, payload in [("tb_cert", 201, "bl2"), ("soc_cert", 603, "bl31"), ("nt_cert", 1201, "bl33")]:
        if extension(certs[cert], oid) != digest_prefix + hashlib.sha256(entries[payload]).digest():
            raise ValueError(f"Payload digest differs from its certificate: {payload}")
    for name in ("trusted_key", "soc_key", "nt_key", "tb_cert", "soc_cert", "nt_cert"):
        counter = 2 if name in ("nt_key", "nt_cert") else 1
        if extension(certs[name], counter) != b"\x02\x01\x00":
            raise ValueError(f"Unsupported nonzero firmware NV counter: {name}")
    return {"root_public_key_sha256": hashlib.sha256(pub_der(certs["trusted_key"].public_key())).hexdigest(),
            "certificate_signatures_verified": 6, "public_key_links_verified": 5, "payload_hashes_verified": 3}


def verify(data, stock=None):
    entries = loader_entries(data)
    chain = verify_chain(entries)
    if stock is not None:
        original = loader_entries(stock)
        if any(original[name] != entries[name] for name in ("bl2", "bl31")) or \
                stock[:0x40000] != data[:0x40000] or stock[0x1c0000:] != data[0x1c0000:]:
            raise ValueError("Loader changes the original BL2, BL31, GPT or reserved area")
    return {"boot_sha256": hashlib.sha256(data).hexdigest(), "boot_bytes": len(data),
            "payloads": {name: {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
                         for name, value in entries.items()}, **chain,
            "hardware_validation": "pending; cryptographic consistency does not prove device acceptance or current OTP state"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("loader", type=Path)
    parser.add_argument("--stock-boot", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.loader.read_bytes(), args.stock_boot.read_bytes() if args.stock_boot else None), indent=2))
