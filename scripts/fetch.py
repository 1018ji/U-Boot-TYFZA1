#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fetch exact public source revisions into this repository's ignored cache."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True)


for source in json.loads((ROOT / "source-lock.json").read_text()).values():
    path = ROOT / "sources" / source["directory"]
    if path.exists():
        actual = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
        if actual != source["commit"]:
            raise SystemExit(f"Existing source differs from the lock: {path}; leave it intact and resolve the cache explicitly")
        print(f"Pinned source present: {path.name}")
        continue
    path.mkdir(parents=True)
    run(path, "init")
    run(path, "remote", "add", "origin", source["url"])
    run(path, "fetch", "--depth=1", "--filter=blob:none", "origin", source["commit"])
    if "subdirectory" in source:
        run(path, "sparse-checkout", "set", source["subdirectory"])
    run(path, "checkout", "--detach", "FETCH_HEAD")
