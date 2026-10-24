#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the production HTTP partition writer on physical NAND images."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BLOCK, SIZE = 0x20000, 0x80000


class StorageWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        http = (ROOT / 'build/u-boot/net/lwip/httpd.c').read_text()
        transfer = http[http.index('static bool mtd_uses_pages(const struct mtd_info *mtd)\n{'):
                        http.index('static int run_flash_all(void)\n{')]
        begin = http.find('static int storage_mtd_check_write(')
        if begin < 0:
            begin = http.index('static int run_storage_job(void)\n{')
        job = http[begin:
                   http.index('/* FIP UUIDs identify BL2')]
        prelude = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <zlib.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef unsigned long long u64;
typedef unsigned long ulong;
#define CONFIG_TARGET_TYFZA1 1
#define CONFIG_IS_ENABLED(name) 0
#define CONFIG_SYS_LOAD_ADDR 0x10000000
#define CMD_RET_FAILURE 1
#define CMD_RET_SUCCESS 0
#define CHUNKSZ_CRC32 0x10000
#define min_t(type,a,b) ((type)(a)<(type)(b)?(type)(a):(type)(b))
#define round_down(n,d) ((n)/(d)*(d))
#define MTD_NANDFLASH 4
#define MTD_MLCNANDFLASH 8
#define HTTP_STORAGE_MTD 1
#define HTTP_STORAGE_UBI 2
#define HTTP_STORAGE_OP_READ 1
#define HTTP_STORAGE_OP_WRITE 2
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
struct mtd_info {int type;u64 size;unsigned int erasesize,writesize;const char *name;struct mtd_info *parent;};
struct erase_info {struct mtd_info *mtd;u64 addr;size_t len;};
struct http_storage_request {int kind,operation;char target[32],partition[32];u64 offset;size_t size;};
static struct mtd_info whole={MTD_NANDFLASH,0x400000,0x20000,0x800,"nand0",NULL};
static struct mtd_info boot={MTD_NANDFLASH,0x200000,0x20000,0x800,"boot",&whole};
static struct mtd_info data={MTD_NANDFLASH,0x80000,0x20000,0x800,"data",&whole};
static unsigned char flash[0x400000];
static struct http_storage_request storage_request,backup_request;
static bool backup_ready;
static ulong backup_at,upload_addr;
static const char *phase;
static long bad_at,error_at,corrupt_at;
static unsigned int erases,writes,references;
static size_t physical(struct mtd_info *m,size_t off){return off+(m==&data?0x200000:0);}
static int mtd_is_partition(struct mtd_info *m){return m->parent!=NULL;}
static void service_network(void) {}
static int mtd_probe_devices(void){return 0;}
static struct mtd_info *get_mtd_device_nm(const char *name){
 struct mtd_info *m=!strcmp(name,"data")?&data:!strcmp(name,"boot")?&boot:!strcmp(name,"nand0")?&whole:NULL;
 if(m)references++;return m?m:(void *)(uintptr_t)-ENODEV;
}
static void put_mtd_device(struct mtd_info *m){(void)m;references--;}
static int mtd_block_isbad(struct mtd_info *m,u64 off){
 if(off>=m->size)return -EINVAL;
 long at=physical(m,off/m->erasesize*m->erasesize);
 return at==error_at?-EIO:at==bad_at;
}
static int mtd_erase(struct mtd_info *m,struct erase_info *e){
 if(e->addr+e->len>m->size || mtd_block_isbad(m,e->addr))return -EIO;
 memset(flash+physical(m,e->addr),0xff,e->len);erases++;return 0;
}
static int mtd_write(struct mtd_info *m,u64 off,size_t n,size_t *done,const void *in){
 if(off+n>m->size || mtd_block_isbad(m,off))return -EIO;
 memcpy(flash+physical(m,off),in,n);*done=n;writes++;return 0;
}
static int mtd_read(struct mtd_info *m,u64 off,size_t n,size_t *done,void *out){
 if(off+n>m->size || mtd_block_isbad(m,off))return -EIO;
 memcpy(out,flash+physical(m,off),n);*done=n;
 if((long)physical(m,off)==corrupt_at && n)((u8 *)out)[0]^=1;
 return 0;
}
static ulong env_get_ulong(const char *key,int base,ulong fallback){(void)key;(void)base;(void)fallback;return upload_addr;}
static void *map_sysmem(ulong addr,size_t size){(void)size;return (void *)addr;}
static void unmap_sysmem(void *p){(void)p;}
static bool upload_region_valid(ulong addr,size_t size){return addr && size;}
static ulong get_timer(ulong start){(void)start;return 0;}
static u32 crc32_wd(u32 seed,const void *p,size_t n,size_t chunk){(void)chunk;return crc32(seed,p,n);}
static int ubi_part(const char *p,const char *v){(void)p;(void)v;return -ENOSYS;}
static int ubi_volume_get_size(const char *name,size_t *used,size_t *capacity){(void)name;(void)used;(void)capacity;return -ENOSYS;}
static int ubi_volume_write(const char *name,const void *p,size_t off,size_t n){(void)name;(void)p;(void)off;(void)n;return -ENOSYS;}
static int ubi_volume_read(const char *name,void *p,size_t off,size_t n){(void)name;(void)p;(void)off;(void)n;return -ENOSYS;}
'''
        tail = r'''
int run(const char *target,const void *image,size_t size,size_t offset,int bad,int fault){
 memset(flash,0xa5,sizeof(flash));erases=writes=references=0;
 bad_at=bad<0?-1:0x200000+bad*0x20000;
 error_at=fault==1?0x260000:-1;corrupt_at=fault==2?0x260000:-1;
 upload_addr=(ulong)image;memset(&storage_request,0,sizeof(storage_request));
 strcpy(storage_request.target,target);storage_request.kind=HTTP_STORAGE_MTD;
 storage_request.operation=HTTP_STORAGE_OP_WRITE;storage_request.size=size;storage_request.offset=offset;
 return run_storage_job();
}
int backup(const char *target){
 erases=writes=references=0;memset(&storage_request,0,sizeof(storage_request));
 strcpy(storage_request.target,target);storage_request.kind=HTTP_STORAGE_MTD;
 storage_request.operation=HTTP_STORAGE_OP_READ;return run_storage_job();
}
unsigned int metric(int key){return key==0?erases:key==1?writes:references;}
void copy_flash(void *out,size_t offset,size_t size){memcpy(out,flash+offset,size);}
'''
        work = ROOT / 'build/storage-write-test'
        work.mkdir(parents=True, exist_ok=True)
        source = work / 'storage.c'
        source.write_text(prelude + transfer + job + tail)
        library = work / 'storage.so'
        subprocess.run(['cc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-Wno-misleading-indentation', '-Wno-unused-function', str(source),
                        '-lz', '-o', str(library)], check=True)
        cls.lib = C.CDLL(str(library))
        cls.lib.run.argtypes = [C.c_char_p, C.c_void_p, C.c_size_t, C.c_size_t, C.c_int, C.c_int]
        cls.lib.backup.argtypes = [C.c_char_p]
        cls.lib.copy_flash.argtypes = [C.c_void_p, C.c_size_t, C.c_size_t]

    def write(self, image, target='data', offset=0, bad=-1, fault=0):
        self.buffer = C.create_string_buffer(bytes(image))
        result = self.lib.run(target.encode(), self.buffer, len(image), offset, bad, fault)
        self.assertEqual(self.lib.metric(2), 0, 'MTD reference leaked')
        return result

    def flash(self, offset, size):
        result = C.create_string_buffer(size)
        self.lib.copy_flash(result, offset, size)
        return result.raw

    def image(self, bad=-1):
        return b''.join(bytes([0xff if index == bad else index + 1]) * BLOCK for index in range(4))

    def test_physical_offsets_and_ff_gaps_survive_partition_write(self):
        for bad in (-1, 0, 1, 3):
            with self.subTest(bad=bad):
                image = self.image(bad)
                self.assertEqual(self.write(image, bad=bad), 0)
                for index in range(4):
                    expected = b'\xa5' * BLOCK if index == bad else image[index * BLOCK:(index + 1) * BLOCK]
                    self.assertEqual(self.flash(0x200000 + index * BLOCK, BLOCK), expected)
                self.assertEqual(self.flash(0, 0x200000), b'\xa5' * 0x200000)
                self.assertEqual(self.lib.metric(0), 4 - (bad >= 0))

    def test_non_ff_payload_for_bad_block_is_rejected_before_erase(self):
        self.assertNotEqual(self.write(self.image(), bad=1), 0)
        self.assertEqual(self.lib.metric(0), 0)
        self.assertEqual(self.lib.metric(1), 0)
        self.assertEqual(self.flash(0x200000, SIZE), b'\xa5' * SIZE)

    def test_subrange_bad_gap_preserves_bytes_outside_requested_range(self):
        image = b'\xff' * BLOCK + b'\x03' * BLOCK
        self.assertEqual(self.write(image, offset=BLOCK, bad=1), 0)
        self.assertEqual(self.flash(0x200000, 2 * BLOCK), b'\xa5' * (2 * BLOCK))
        self.assertEqual(self.flash(0x240000, BLOCK), b'\x03' * BLOCK)
        self.assertEqual(self.flash(0x260000, BLOCK), b'\xa5' * BLOCK)
        self.assertEqual(self.lib.metric(0), 1)

    def test_late_bad_block_query_error_is_rejected_before_erase(self):
        self.assertNotEqual(self.write(self.image(), fault=1), 0)
        self.assertEqual(self.lib.metric(0), 0)
        self.assertEqual(self.flash(0x200000, SIZE), b'\xa5' * SIZE)

    def test_raw_boot_and_whole_flash_writes_are_rejected_before_erase(self):
        for target in ('boot', 'nand0'):
            with self.subTest(target=target):
                self.assertNotEqual(self.write(b'\xff' * 0x200000, target=target), 0)
                self.assertEqual(self.lib.metric(0), 0)
                self.assertEqual(self.flash(0, 0x200000), b'\xa5' * 0x200000)

    def test_range_and_alignment_errors_leave_flash_intact(self):
        for image, offset in ((b'\xff' * SIZE, BLOCK), (b'\xff' * (BLOCK - 1), 0),
                              (b'\xff' * BLOCK, 0x800)):
            with self.subTest(size=len(image), offset=offset):
                self.assertNotEqual(self.write(image, offset=offset), 0)
                self.assertEqual(self.lib.metric(0), 0)

    def test_boot_and_whole_flash_backups_remain_available(self):
        for target in (b'boot', b'nand0'):
            self.assertEqual(self.lib.backup(target), 0)
            self.assertEqual(self.lib.metric(0), 0)
            self.assertEqual(self.lib.metric(2), 0)

    def test_readback_corruption_is_reported(self):
        self.assertNotEqual(self.write(self.image(), fault=2), 0)


if __name__ == '__main__':
    unittest.main()
