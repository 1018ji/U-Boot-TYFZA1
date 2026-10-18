#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build fixed TF-A host tools with the certificate extension set used by Taurus."""
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def build():
    pinned = json.loads((ROOT / "source-lock.json").read_text())["reference"]["commit"]
    reference = ROOT / "sources/uboot-an758x"
    work = ROOT / "build/firmware-tools"
    marker = work / "source.json"
    source = work / "tf-a"
    if source.exists():
        if json.loads(marker.read_text()) != {"commit": pinned}:
            raise ValueError("Host-tool source revision differs from source-lock.json")
    else:
        work.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(["git", "-C", str(reference), "archive", pinned, "tf-a"], stdout=subprocess.PIPE)
        with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
            archive.extractall(work, filter="data")
        if proc.wait():
            raise RuntimeError("Unable to prepare TF-A host tools")
        marker.write_text(json.dumps({"commit": pinned}) + "\n")
    relative = "tf-a/tools/cert_create/src/tbbr/tbb_cert.c"
    text = subprocess.check_output(["git", "-C", str(reference), "show", f"{pinned}:{relative}"], text=True)
    # Original TF-A 1.5 certificates omit the newer FW_CONFIG/SOC_CONFIG/NT_CONFIG hashes.
    # Keep the exact legacy critical OID set, rather than relying on old parsers ignoring it.
    patches = [
        ("HW_CONFIG_HASH_EXT,\n\t\t\tFW_CONFIG_HASH_EXT\n\t\t},\n\t\t.num_ext = 5",
         "HW_CONFIG_HASH_EXT\n\t\t},\n\t\t.num_ext = 4"),
        ("SOC_AP_FW_HASH_EXT,\n\t\t\tSOC_FW_CONFIG_HASH_EXT,\n\t\t},\n\t\t.num_ext = 3",
         "SOC_AP_FW_HASH_EXT\n\t\t},\n\t\t.num_ext = 2"),
        ("NON_TRUSTED_WORLD_BOOTLOADER_HASH_EXT,\n\t\t\tNON_TRUSTED_FW_CONFIG_HASH_EXT,\n\t\t},\n\t\t.num_ext = 3",
         "NON_TRUSTED_WORLD_BOOTLOADER_HASH_EXT\n\t\t},\n\t\t.num_ext = 2"),
    ]
    for old, new in patches:
        if text.count(old) != 1:
            raise ValueError("TF-A certificate profile source contract changed")
        text = text.replace(old, new)
    cert_source = source / "tools/cert_create/src/tbbr/tbb_cert.c"
    if cert_source.read_text() != text:
        cert_source.write_text(text)
    for directory in ("fiptool", "cert_create"):
        subprocess.run(["make", "-C", str(source / "tools" / directory)], check=True)
    return {name: source / "tools" / name / name for name in ("fiptool", "cert_create")}


if __name__ == "__main__":
    print(json.dumps({name: str(path) for name, path in build().items()}))
