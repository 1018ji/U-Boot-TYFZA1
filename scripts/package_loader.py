#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build a per-device Taurus candidate loader, retaining its GPT, BL2 and BL31."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from build_host_tools import build as build_tools
from verify_loader import UUIDS, FIP_SIZE, FIP_OFFSETS, loader_entries, fip_entries, verify

ROOT = Path(__file__).resolve().parents[1]
CERT_OPTIONS = {"trusted_key": "trusted-key-cert", "soc_key": "soc-fw-key-cert",
                "nt_key": "nt-fw-key-cert", "tb_cert": "tb-fw-cert",
                "soc_cert": "soc-fw-cert", "nt_cert": "nt-fw-cert"}
KEY_OPTIONS = ("rot-key", "trusted-world-key", "non-trusted-world-key", "scp-fw-key",
               "soc-fw-key", "tos-fw-key", "nt-fw-key")


def package(stock_path, bl33_path, out_dir, key_dir):
    stock_path, bl33_path = Path(stock_path), Path(bl33_path)
    out_dir, key_dir = Path(out_dir).resolve(), Path(key_dir).resolve()
    stock = stock_path.read_bytes()
    original = loader_entries(stock)
    verify(stock)
    digest = hashlib.sha256(stock).hexdigest()
    profiles = json.loads((ROOT / "evidence/stock-inputs.json").read_text())
    profile = next((p for p in profiles if p["boot_sha256"] == digest), None)
    if profile is None:
        raise ValueError("Unknown stock baseline: inspect this device's boot layout and add its verified profile first")
    bl33 = bl33_path.read_bytes()
    meta = json.loads(bl33_path.with_suffix(bl33_path.suffix + ".json").read_text())
    if meta.get("qemu_fixture") or meta["bl33_sha256"] != hashlib.sha256(bl33).hexdigest() or \
            meta["run_address"] != "0x4000000" or meta["relocation_address"] != "0x8000000":
        raise ValueError("Expected a matching production-address BL33 wrapper and manifest")
    tools = build_tools()
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "fip-components"
    work.mkdir(exist_ok=True)
    for name in ("bl2", "bl31"):
        (work / (name + ".bin")).write_bytes(original[name])
    (work / "bl33.bin").write_bytes(bl33)
    key_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_args = []
    for option in KEY_OPTIONS:
        path = key_dir / (option + ".pem")
        if not path.exists():
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption())
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as target:
                target.write(private)
        key_args += ["--" + option, str(path)]
    cert_args = []
    for name, option in CERT_OPTIONS.items():
        cert_args += ["--" + option, str(work / (name + ".der"))]
    subprocess.run([str(tools["cert_create"]), "--key-alg", "rsa", "--key-size", "2048",
                    "--hash-alg", "sha256", "--tfw-nvctr", "0", "--ntfw-nvctr", "0",
                    "--tb-fw", str(work / "bl2.bin"), "--soc-fw", str(work / "bl31.bin"),
                    "--nt-fw", str(work / "bl33.bin"), *key_args, *cert_args], check=True)
    fip = out_dir / "taurus.fip"
    subprocess.run([str(tools["fiptool"]), "create", "--tb-fw", str(work / "bl2.bin"),
                    "--soc-fw", str(work / "bl31.bin"), "--nt-fw", str(work / "bl33.bin"),
                    *cert_args, str(fip)], check=True)
    packed = fip.read_bytes()
    if len(packed) > FIP_SIZE:
        raise ValueError(f"FIP is {len(packed)} bytes; slot capacity is {FIP_SIZE}")
    values = fip_entries(packed)
    if any(values[name] != original[name] for name in ("bl2", "bl31")) or values["bl33"] != bl33:
        raise ValueError("Packed firmware payloads differ from their inputs")
    result = bytearray(stock)
    for start in FIP_OFFSETS:
        result[start:start + FIP_SIZE] = packed + b"\xff" * (FIP_SIZE - len(packed))
    report = verify(bytes(result), stock)
    report.update({"variant": profile["variant"], "stock_boot_sha256": digest,
                   "fip_bytes": len(packed), "fip_slot_headroom": FIP_SIZE - len(packed),
                   "bl33_wrapper": meta, "certificate_profile": "Taurus TF-A 1.5 critical extension set",
                   "key_directory": str(key_dir), "otp_written": False})
    output = out_dir / "taurus_spi_nand_loader.img"
    if output.resolve() == stock_path.resolve():
        raise ValueError("Refusing to overwrite the input stock backup")
    output.write_bytes(result)
    (out_dir / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    (out_dir / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256((out_dir / name).read_bytes()).hexdigest()}  {name}\n"
        for name in ("taurus_spi_nand_loader.img", "taurus.fip", "manifest.json")))
    print(json.dumps({"variant": profile["variant"], "loader": str(output),
                      "fip_bytes": len(packed), "fip_slot_headroom": FIP_SIZE - len(packed),
                      "cryptographic_verification": "passed", "hardware_validation": "pending"}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-boot", type=Path, required=True)
    parser.add_argument("--bl33", type=Path, default=ROOT / "output/prototype/bl33.bin")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keys", type=Path, default=ROOT / "keys/development")
    args = parser.parse_args()
    package(args.stock_boot, args.bl33, args.output, args.keys)
