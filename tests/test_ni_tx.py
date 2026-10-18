#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Execute the prepared vendor TX function and decode its XRAM wire length."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class TransmitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        vendor = ROOT/'build/u-boot/board/realtek/tyfza1/vendor'
        source = (vendor/'eth_ni.c').read_text()
        body = source[source.index('static int cortina_ni_send('):source.index('static int cortina_ni_write_hwaddr(')]
        header = (vendor/'eth_ni.h').read_text()
        end = header.index('} NI_HEADER_X_T;') + len('} NI_HEADER_X_T;')
        begin = header.rfind('typedef volatile union',0,end)
        work = ROOT/'build/ni-tx-test'; work.mkdir(parents=True,exist_ok=True)
        prelude = r'''#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32, ca_uint32;
typedef uint16_t u16;
typedef uint8_t u8;
typedef uintptr_t ca_uint;
static u32 xram[2048], cursor;
struct phy_device { int link; };
struct cortina_ni_priv { struct phy_device *phydev; u32 tx_xram_start, tx_xram_end;
 uintptr_t tx_xram_base_adr, tx_xram_end_adr; };
struct udevice { struct cortina_ni_priv *priv; };
static void *dev_get_priv(struct udevice *dev) { return dev->priv; }
#define NI_XRAM_BASE ((uintptr_t)xram)
#define HEADER_A_SIZE 8
#define ETH_NI_DBG 0
#define NI_HV_XRAM_CPUXRAM_CPU_STAT_TX_0 0
#define NI_HV_XRAM_CPUXRAM_CPU_CFG_TX_0 1
#define CORTINA_CA_REG_READ(reg) (cursor)
#define CORTINA_CA_REG_WRITE(value, reg) (cursor = (value))
#define RDWRPTR_ADVANCE_ONE(x, base, max) (((x+1)>=(u32 *)(uintptr_t)(max))?(u32 *)(uintptr_t)(base):x+1)
static void udelay(unsigned int n) { (void)n; }
static u32 crc32(u32 seed, const void *data, unsigned int size) { (void)data; return seed+size; }
typedef union { struct { u32 pkt_wr_ptr:10, reserved:22; } bf; u32 wrd; } NI_HV_XRAM_CPUXRAM_CPU_CFG_TX_0_t;
'''
        tail = r'''
int test_send(const void *data, int length) {
 struct phy_device phy = {1};
 struct cortina_ni_priv priv = { .phydev=&phy, .tx_xram_start=0, .tx_xram_end=1023,
  .tx_xram_base_adr=(uintptr_t)xram, .tx_xram_end_adr=(uintptr_t)(xram+2048) };
 struct udevice dev = { &priv };
 memset(xram,0xcc,sizeof(xram)); cursor=0;
 return cortina_ni_send(&dev,(void *)data,length);
}
int test_wire_length(void) {
 NI_HEADER_X_T header; header.wrd=xram[1];
 unsigned int valid = (header.wrd >> 12) & 7;
 return ((header.bf.next_link-2)*8)-(valid?8-valid:0)-4;
}
int test_frame(const void *data, int length) { return memcmp(xram+4,data,length); }
'''
        cfile=work/'tx.c';cfile.write_text(prelude+header[begin:end]+'\n'+body+tail)
        lib=work/'tx.so'
        subprocess.run(['cc','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
                        '-Wno-unused-but-set-variable',str(cfile),'-o',str(lib)],check=True)
        cls.lib=C.CDLL(str(lib));cls.lib.test_send.argtypes=[C.c_void_p,C.c_int]
        cls.lib.test_frame.argtypes=[C.c_void_p,C.c_int]

    def test_exact_wire_length_and_payload_including_full_mtu(self):
        for length in [42,54,60,61,512,1024,1459,1460,1500,1514,1518]:
            with self.subTest(length=length):
                data=C.create_string_buffer(bytes(i%251 for i in range(length)))
                self.assertEqual(self.lib.test_send(data,length),0)
                self.assertEqual(self.lib.test_wire_length(),max(60,length))
                self.assertEqual(self.lib.test_frame(data,length),0)

    def test_oversize_and_negative_rejected(self):
        data=C.create_string_buffer(2048)
        for length in [-1,1519,2048]:self.assertNotEqual(self.lib.test_send(data,length),0)

if __name__=='__main__':unittest.main()
