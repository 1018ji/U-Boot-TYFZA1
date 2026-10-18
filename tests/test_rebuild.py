#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fault injection into the production UBI rebuild, protecting factory volumes."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RebuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=(ROOT/'overlay/board/realtek/tyfza1/recovery.c').read_text()
        body=source[source.index('int tyfza1_rebuild_ubi('):]
        work=ROOT/'build/rebuild-test';work.mkdir(parents=True,exist_ok=True)
        header=r'''
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define DIV_ROUND_UP(a,b) (((a)+(b)-1)/(b))
struct ubi_volume { char name[32];int reserved_pebs,upd_marker,corrupted; };
struct ubi_device {int ro_mode,avail_pebs,leb_size,beb_rsvd_level,beb_rsvd_pebs;unsigned int vtbl_slots;struct ubi_volume *volumes[128];};
static struct ubi_device dev,*ubi_devices[]={&dev};
static struct ubi_volume vols[128];
static unsigned int removed,created,operations;
static int fault;
static const char *names[]={"ubi_Config","ubi_fpga","ubi_DTB0","ubi_k0","ubi_r0","ubi_DTB1","ubi_k1","ubi_r1","ubi_framework1","ubi_framework2","ubi_apps","rootfs_data"};
static int ubi_part(const char *part,const char *vid) {(void)part;(void)vid;return 0;}
static int env_set(const char *key,const char *value) {(void)key;(void)value;return 0;}
static int env_save(void) {return fault==100?-EIO:0;}
static int ubi_volume_remove(char *name) {
 if(++operations==(unsigned int)fault)return -EIO;
 for(int i=0;i<12;i++)if(!strcmp(name,names[i])) {
  removed|=1U<<i;dev.avail_pebs+=vols[i].reserved_pebs;dev.volumes[i]=NULL;return 0;
 }return -EINVAL;
}
static int run_commandf(const char *fmt,const char *name,unsigned int size,unsigned int id) {
 (void)fmt;if(++operations==(unsigned int)fault)return -EIO;
 int lebs=size?(int)DIV_ROUND_UP(size,dev.leb_size):dev.avail_pebs;
 if(lebs>dev.avail_pebs)return -ENOSPC;
 created|=1U<<id;strcpy(vols[id].name,name);vols[id].reserved_pebs=lebs;
 dev.volumes[id]=&vols[id];dev.avail_pebs-=lebs;return 0;
}
static void poll(void) {}
'''
        tail=r'''
void reset(int failure,int extra) {
 memset(&dev,0,sizeof(dev));memset(vols,0,sizeof(vols));removed=created=operations=0;fault=failure;
 dev.leb_size=126976;dev.avail_pebs=extra;dev.vtbl_slots=128;
 int lebs[]={50,34,3,50,265,3,50,265,133,133,793,133};
 for(int i=0;i<12;i++) {strcpy(vols[i].name,names[i]);vols[i].reserved_pebs=lebs[i];dev.volumes[i]=&vols[i];}
}
void unknown(void) {strcpy(vols[12].name,"customer_calibration");dev.volumes[12]=&vols[12];}
int run(void) {return tyfza1_rebuild_ubi(poll);}
unsigned int metric(int key) {return key==0?removed:key==1?created:operations;}
int factory_intact(void) {
 int ids[]={0,1,2,5};for(int i=0;i<4;i++)if(dev.volumes[ids[i]]!=&vols[ids[i]]||strcmp(vols[ids[i]].name,names[ids[i]]))return 0;
 return 1;
}
'''
        path=work/'rebuild.c';path.write_text(header+body+tail);lib=work/'rebuild.so'
        subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
                        str(path),'-o',str(lib)],check=True)
        cls.lib=C.CDLL(str(lib))

    def test_no_factory_removal_in_success_or_any_failure(self):
        self.lib.reset(0,10);self.assertEqual(self.lib.run(),0)
        operations=self.lib.metric(2)
        for failure in range(1,operations+1):
            self.lib.reset(failure,10)
            self.assertNotEqual(self.lib.run(),0)
            self.assertEqual(self.lib.factory_intact(),1)
            self.assertEqual((self.lib.metric(0)|self.lib.metric(1))&0x27,0)

    def test_insufficient_space_refused_before_removal(self):
        self.lib.reset(0,-1);self.assertNotEqual(self.lib.run(),0)
        self.assertEqual(self.lib.metric(2),0)

    def test_unknown_volume_refused_before_removal(self):
        self.lib.reset(0,10);self.lib.unknown();self.assertNotEqual(self.lib.run(),0)
        self.assertEqual(self.lib.metric(2),0)

    def test_environment_failure_refused_before_removal(self):
        self.lib.reset(100,10);self.assertNotEqual(self.lib.run(),0)
        self.assertEqual(self.lib.metric(2),0)


if __name__=='__main__':unittest.main()
