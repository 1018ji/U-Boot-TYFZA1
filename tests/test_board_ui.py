#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute GPIO sampling and LAN lamp ordering against a register model."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BoardUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work = ROOT/'build/board-ui-test'
        work.mkdir(parents=True, exist_ok=True)
        body = '\n'.join(line for line in (ROOT/'overlay/board/realtek/tyfza1/board-ui.c').read_text().splitlines()
                         if not line.startswith('#include'))
        prelude = r'''
#include <stdint.h>
#include <string.h>
typedef uint32_t u32;
static u32 mux, dir, output, input, frames[4];
static unsigned int nframes, delay;
static const char *variant;
static u32 readl(uintptr_t addr) {
 if(addr==0xf4320100)return mux;
 if(addr==0xf43292c0)return dir;
 if(addr==0xf43292c4)return output;
 return input;
}
static void writel(u32 value,uintptr_t addr) {
 if(addr==0xf4320100)mux=value;
 if(addr==0xf43292c0)dir=value;
 if(addr==0xf43292c4)output=value;
}
#define setbits_le32(a,b) writel(readl(a)|(b),a)
#define clrbits_le32(a,b) writel(readl(a)&~(b),a)
#define clrsetbits_le32(a,b,c) writel((readl(a)&~(b))|(c),a)
static const char *env_get(const char *name) {(void)name;return variant;}
static void udelay(unsigned int us) {delay+=us;}
static void mdelay(unsigned int ms) {delay+=ms*1000;if(nframes<4)frames[nframes++]=output;}
'''
        tail = r'''
void reset(int two,u32 value,int pressed) {
 mux=dir=output=value;input=pressed?0:1U<<8;delay=nframes=0;
 variant=two==2?"unknown":two?"2p5g":"4ge";
}
u32 metric(int key) {
 if(key==0)return mux;if(key==1)return dir;if(key==2)return output;
 if(key==3)return nframes;if(key==4)return delay;return frames[key-5];
}
'''
        path = work/'board.c'; path.write_text(prelude+body+tail)
        lib = work/'board.so'
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
                        '-Wno-misleading-indentation',str(path),'-o',str(lib)],check=True)
        cls.lib=C.CDLL(str(lib));cls.lib.metric.restype=C.c_uint

    def test_each_lan_lights_in_order_and_original_registers_return(self):
        for two,pins,low in [(0,[4,3,1,0],0x1b),(1,[11,12,3,4],0x18)]:
            for seed in (0,0xa5a5a5a5,0xffffffff):
                self.lib.reset(two,seed,0);self.lib.tyfza1_boot_leds()
                mask=sum(1<<pin for pin in pins)
                self.assertEqual(self.lib.metric(3),4)
                self.assertEqual(self.lib.metric(4),600000)
                for i,pin in enumerate(pins):
                    frame=self.lib.metric(i+5)
                    self.assertEqual(frame & mask,low^(1<<pin))
                    self.assertEqual(frame & ~mask,seed & ~mask)
                for key in range(3):self.assertEqual(self.lib.metric(key),seed)

    def test_reset_active_low_sampling_changes_only_gpio8(self):
        for pressed in (0,1):
            self.lib.reset(1,0xa5a5a5a5,pressed)
            self.assertEqual(self.lib.tyfza1_reset_held(),pressed)
            self.assertEqual(self.lib.metric(0),0xa5a5a5a5|0x100)
            self.assertEqual(self.lib.metric(1),0xa5a5a5a5|0x100)
            self.assertEqual(self.lib.metric(2),0xa5a5a5a5)

    def test_unknown_board_does_not_drive_lamps(self):
        self.lib.reset(2,0xa5a5a5a5,0);self.lib.tyfza1_boot_leds()
        self.assertEqual(self.lib.metric(3),0)


if __name__=='__main__':unittest.main()
