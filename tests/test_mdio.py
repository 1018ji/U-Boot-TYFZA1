#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run both phases of production C45 access with W1C and timeout behavior."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]


class MdioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work=ROOT/'build/mdio-test';work.mkdir(parents=True,exist_ok=True)
        header=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32,ca_uint32_t;
typedef uint16_t u16,ca_uint16_t;
typedef int ca_status_t;
#define BIT(n) (1U<<(n))
#define PER_MDIO_CTRL 0x10
#define PER_MDIO_ADDR 4
#define PER_MDIO_WRDATA 8
#define PER_MDIO_RDDATA 12
static unsigned int addresses[2],values[2],starts,clears,delay,reads,failed_phase;
static u32 control;
static void writel(u32 value,unsigned long reg) {
 if(reg==PER_MDIO_ADDR && starts<2)addresses[starts]=value;
 if(reg==PER_MDIO_WRDATA && starts<2)values[starts]=value;
 if(reg==PER_MDIO_CTRL) {
  if(value&1){control&=~1U;clears++;}
  if(value&128){starts++;reads=0;}
 }
}
static u32 readl(unsigned long reg) {
 if(reg==PER_MDIO_RDDATA)return 0xc848;
 if(starts!=failed_phase && ++reads>=3)control|=1;
 return control;
}
static void udelay(unsigned int us) {delay+=us;}
'''
        tail=r'''
int run(int write_op,int fail) {
 starts=clears=delay=reads=0;failed_phase=fail;control=1;
 u16 data=0;
 if(write_op)return __ca_mdio_c45_write(7,31,0xa436,0x8024);
 int ret=__ca_mdio_c45_read(7,1,3,&data);return ret?ret:data;
}
unsigned int metric(int key) {
 switch(key){case 0:return starts;case 1:return clears;case 2:return delay;
 case 3:return addresses[0];case 4:return addresses[1];case 5:return values[0];case 6:return values[1];}return 0;
}
'''
        path=work/'mdio.c'
        path.write_text(header+(ROOT/'overlay/board/realtek/tyfza1/mdio.inc').read_text()+tail)
        lib=work/'mdio.so'
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',str(path),'-o',str(lib)],check=True)
        cls.lib=C.CDLL(str(lib));cls.lib.run.argtypes=[C.c_int,C.c_int]

    def test_c45_read_and_write_encode_both_phases(self):
        self.assertEqual(self.lib.run(0,0),0xc848)
        self.assertEqual([self.lib.metric(i) for i in (0,1,3,4,5)],[2,4,0x10107,0xd8107,3])
        self.assertEqual(self.lib.run(1,0),0)
        self.assertEqual([self.lib.metric(i) for i in (0,1,3,4,5,6)],[2,4,0x11f07,0x51f07,0xa436,0x8024])

    def test_stale_done_is_cleared_and_timeout_stops_next_phase(self):
        for op in (0,1):
            for failed_phase in (1,2):
                self.assertEqual(self.lib.run(op,failed_phase),-110)
                self.assertEqual(self.lib.metric(0),failed_phase)
                self.assertGreaterEqual(self.lib.metric(2),50000)
                self.assertLess(self.lib.metric(2),50100)


if __name__=='__main__':unittest.main()
