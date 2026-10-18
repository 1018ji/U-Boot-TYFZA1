#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute board init with an armed watchdog and no scratch success marker."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

class BootWatchdogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=(ROOT/'overlay/board/realtek/tyfza1/tyfza1.c').read_text()
        body=source[source.index('int board_init('):source.index('void board_preboot_os(')]
        prelude=r'''
#include <stdint.h>
#include <stdbool.h>
#define PER_WDT_CTRL 0xf432901cUL
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
typedef uint32_t u32;
static u32 original_xram[0x2000/4];
static bool reset_requested;
static unsigned int watchdog,order,disabled_at,reset_at,ethernet_at;
static void writel(u32 value,uintptr_t address) {
 order++;if(address==PER_WDT_CTRL){watchdog=value;disabled_at=order;}
}
static u32 readl(uintptr_t address) {(void)address;return 0;}
static int tyfza1_reset_held(void) {reset_at=++order;return 1;}
void ca77xx_eth_change_default(void) {ethernet_at=++order;}
'''
        tail=r'''
int run(unsigned int armed) {watchdog=armed;order=disabled_at=reset_at=ethernet_at=0;return board_init();}
unsigned int metric(int which) {switch(which){case 0:return watchdog;case 1:return disabled_at;case 2:return reset_at;case 3:return ethernet_at;case 4:return reset_requested;}return 0;}
'''
        work=ROOT/'build/watchdog-test';work.mkdir(parents=True,exist_ok=True)
        path=work/'watchdog.c';path.write_text(prelude+body+tail)
        lib=work/'watchdog.so'
        subprocess.run(['cc','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',str(path),'-o',str(lib)],check=True)
        cls.lib=C.CDLL(str(lib))
    def test_armed_watchdog_stops_before_button_and_ethernet(self):
        for value in (0,1,0x1003,0xffffffff):
            self.assertEqual(self.lib.run(value),0)
            self.assertEqual(self.lib.metric(0),0)
            self.assertEqual(self.lib.metric(1),1)
            self.assertLess(self.lib.metric(1),self.lib.metric(2))
            self.assertLess(self.lib.metric(2),self.lib.metric(3))
            self.assertEqual(self.lib.metric(4),1)

if __name__=='__main__':unittest.main()
