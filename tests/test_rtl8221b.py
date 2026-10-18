#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check the U-Boot PHY callbacks and optional exact OEM ARM64 execution trace."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "overlay/board/realtek/tyfza1"
WORK = ROOT / "build/rtl8221b-test"
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--stock-module", type=Path)
parser.add_argument("--oracle-project", type=Path)
ARGS, REST = parser.parse_known_args()


class Rtl8221bTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        WORK.mkdir(parents=True, exist_ok=True)
        source = WORK / "phy.c"
        production = "\n".join(line for line in (BOARD / "rtl8221b.c").read_text().splitlines()
                               if not line.startswith("#include <"))
        source.write_text('#include "rtl8221b_io.h"\n' + production + r'''
int run(unsigned int rev, unsigned int ver, unsigned int seed, unsigned int fault, unsigned int timeout, int full) {
 revision=rev; version=ver; count=accesses=0; fail_at=fault; timeout_reg=timeout;
 physr=4; link_up=false;
 for(unsigned int m=0;m<32;m++)for(unsigned int r=0;r<65536;r++)registers[m][r]=seed;
 struct phy_device phy={.is_c45=true,.addr=7};
 return full ? rtl8221b_config(&phy) : rtl8221b_tyfza1_config_init(&phy);
}
unsigned int event_count(void) { return count; }
const void *event_data(void) { return events; }
int status(int link, unsigned int bits, int fault, int *output) {
 count=accesses=0; fail_at=fault; timeout_reg=0; link_up=link; physr=bits;
 struct phy_device phy={.is_c45=true,.addr=7};
 int ret=rtl8221b_startup(&phy);
 output[0]=phy.link;output[1]=phy.speed;output[2]=phy.duplex;return ret;
}
unsigned int register_value(unsigned int mmd,unsigned int reg) { return registers[mmd][reg]; }
''')
        lib = WORK / "phy.so"
        subprocess.run(["cc", "-shared", "-fPIC", "-O2", "-Wall", "-Wextra", "-Werror",
            "-I" + str(ROOT / "tests"), "-I" + str(BOARD), str(source), "-o", str(lib)], check=True)
        cls.lib = C.CDLL(str(lib))
        cls.lib.run.argtypes = [C.c_uint] * 5 + [C.c_int]
        cls.lib.event_data.restype = C.POINTER(C.c_uint)
        cls.lib.status.argtypes = [C.c_int, C.c_uint, C.c_int, C.POINTER(C.c_int)]
        cls.rows = []

    def trace(self):
        data = self.lib.event_data()
        return [[chr(data[4*i]), *data[4*i+1:4*i+4]] for i in range(self.lib.event_count())]

    def test_initialization_variants_and_each_bus_failure(self):
        for rev, version in [(8, 0), (8, 0x20), (9, 0), (10, 0)]:
            self.assertEqual(self.lib.run(rev, version, 0xa5a5, 0, 0, 0), 0)
            count = self.lib.event_count()
            expected_count = 1093 if rev == 8 and version != 0x20 else 19
            self.assertEqual(count, expected_count)
            for access in range(1, count+1):
                self.assertEqual(self.lib.run(rev, version, 0xa5a5, access, 0, 0), -5,
                                 f"rev {rev}: MDIO error at operation {access} was lost")

    def test_poll_timeouts(self):
        for register in (0xa420, 0xb800, 0xa434):
            self.assertEqual(self.lib.run(8, 0, 0, 0, register, 0), -110)

    def test_copper_and_negotiation_enabled_after_hsgmii(self):
        self.assertEqual(self.lib.run(8, 0x20, 0xa5a5, 0, 0, 1), 0)
        value = self.lib.register_value
        self.assertEqual(value(1, 0) & (1 << 11), 0)
        self.assertEqual(value(31, 0xa408) & 0x1e0, 0x140)
        self.assertEqual(value(31, 0xa412) & 0x300, 0x200)
        self.assertEqual(value(31, 0xa5d4) & 0x80, 0x80)
        self.assertEqual(value(7, 0) & 0x1200, 0x1200)

    def test_status_speeds_and_errors(self):
        out = (C.c_int * 3)()
        for bits, speed in [(0, 10), (0x10, 100), (0x20, 1000), (0x210, 2500)]:
            for duplex in (0, 1):
                self.assertEqual(self.lib.status(1, bits | (duplex << 3), 0, out), 0)
                self.assertEqual(list(out), [1, speed, duplex])
        self.assertEqual(self.lib.status(0, 0, 0, out), 0); self.assertEqual(out[0], 0)
        self.assertEqual(self.lib.status(1, 0x220, 0, out), -22); self.assertEqual(out[0], 0)
        for fail in (1, 2, 3):
            self.assertEqual(self.lib.status(1, 0x218, fail, out), -5)
            self.assertEqual(out[0], 0)

    @unittest.skipUnless(ARGS.stock_module and ARGS.oracle_project, "OEM module/oracle not supplied")
    def test_exact_original_arm64_execution(self):
        sys.path[:0] = [str(ARGS.oracle_project / "tools"), str(ARGS.oracle_project / "analysis/python-deps")]
        from arm64_module_oracle import ModuleOracle
        from unicorn.arm64_const import UC_ARM64_REG_X4
        self.assertEqual(hashlib.sha256(ARGS.stock_module.read_bytes()).hexdigest(),
                         "0ba23162b42e457b0628b0899e89883198aac919a14ddab91997fd9ef5710652")
        for revision, version, seed in [(8, 0, 0), (8, 0, 0xa5a5), (8, 0x20, 0xa5a5), (9, 0, 0xa5a5), (10, 0, 0xa5a5)]:
            registers, events = {}, []
            def io(name, values):
                if name == "MmdPhyRead":
                    mmd, reg = values[2], values[3] & 0xffff
                    value = registers.get((mmd, reg), seed)
                    if (mmd, reg) == (31, 0xa420): value = 3
                    if (mmd, reg) == (1, 3): value = 0xc840 | revision
                    if (mmd, reg) == (31, 0xa438) and registers.get((31, 0xa436)) == 0x801e: value = version
                    if (mmd, reg) == (31, 0xb800): value = 0x40 if registers.get((31, 0xb820), 0) & 0x10 else 0
                    if (mmd, reg) == (31, 0xa434): value = 4
                    oracle.uc.mem_write(oracle.uc.reg_read(UC_ARM64_REG_X4), struct.pack("<H", value))
                    events.append(["r", mmd, reg, value]); return 1
                if name == "MmdPhyWrite":
                    mmd, reg = values[2], values[3] & 0xffff
                    value = oracle.uc.reg_read(UC_ARM64_REG_X4) & 0xffff
                    registers[mmd, reg] = value
                    events.append(["w", mmd, reg, value]); return 1
                if name in ("printk", "osal_time_udelay"): return 0
                raise AssertionError((name, values))
            oracle = ModuleOracle(ARGS.stock_module, ["Rtl8221_phy_init", "Rtl8221_enable_set",
                "Rtl8221_wait_for_bit.constprop.0", "Rtl8221_serdes_option_set"], io)
            self.assertEqual(oracle.call("Rtl8221_phy_init", 0, 7, instruction_budget=500000), 1)
            self.assertEqual(oracle.call("Rtl8221_serdes_option_set", 0, 7, 1), 1)
            self.assertEqual(self.lib.run(revision, version, seed, 0, 0, 0), 0)
            self.assertEqual(self.trace(), events)
            self.rows.append({"revision": revision, "patch_version": version, "seed": seed,
                "events": len(events), "trace_sha256": hashlib.sha256(json.dumps(events).encode()).hexdigest()})
        (ROOT / "evidence/rtl8221b-oem.json").write_text(json.dumps({
            "scope": "Actual U-Boot initialization compared event-for-event with original ARM64 OEM functions; PHY bus and timers simulated",
            "module_sha256": hashlib.sha256(ARGS.stock_module.read_bytes()).hexdigest(), "runs": self.rows}, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0], *REST])
