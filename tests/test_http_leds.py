#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise recovery job/upload LED transitions using the production HTTP helpers."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HttpLedsTests(unittest.TestCase):
    def test_jobs_uploads_restore_and_failures(self):
        header = (ROOT / 'overlay/include/tyfza1_recovery.h').read_text()
        states = header[header.index('enum tyfza1_leds {'):header.index('void tyfza1_recovery_leds(')]
        helper = (ROOT / 'overlay/include/net/tyfza1-httpd.inc').read_text()
        helper = helper[helper.index('static int run_captured_job(void);'):]
        code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
''' + states + r'''
enum { HTTP_JOB_NONE,HTTP_JOB_BL2,HTTP_JOB_FIP,HTTP_JOB_BOARD_DATA,HTTP_JOB_REBUILD,
 HTTP_JOB_FIRMWARE,HTTP_JOB_FLASH_ALL,HTTP_JOB_NAND_SCRUB,HTTP_JOB_STORAGE,HTTP_JOB_TYF_RESTORE };
enum {HTTP_STORAGE_OP_READ,HTTP_STORAGE_OP_WRITE,HTTP_POST_TASK,HTTP_POST_UPLOAD,HTTP_POST_FLASH_ALL_UPLOAD};
struct tyfza1_restore_status {bool active;size_t next,total;};
static struct tyfza1_restore_status restore;
static struct {int operation;} storage_request;
static struct {void *connection;int kind;} post_state;
static int job_kind,result,clear_restore,polls,calls,trace[8];
static size_t buffer_size=4096,done,total;
static char tyf_restore_operation[24];
static const struct tyfza1_restore_status *tyfza1_restore_status(void){return &restore;}
static void tyfza1_recovery_leds(enum tyfza1_leds state){assert(calls<8);trace[calls++]=state;}
static void tyfza1_recovery_leds_busy(size_t d,size_t t){done=d;total=t;tyfza1_recovery_leds(TYFZA1_LEDS_BUSY);}
static size_t tyfza1_loader_write_size(void){return 0x200000;}
static void tyfza1_recovery_leds_poll(void){polls++;}
''' + helper + r'''
static int run_captured_job(void){
 if(restore.active)restore.next+=buffer_size;
 if(clear_restore)restore.active=false;
 return result;
}
int main(void){
 for(int job=HTTP_JOB_BL2;job<=HTTP_JOB_NAND_SCRUB;job++)for(int fail=0;fail<2;fail++){
  job_kind=job;result=fail?-5:0;calls=0;
  assert(tyf_http_run_job()==result && calls==2 && trace[0]==TYFZA1_LEDS_BUSY);
  assert(trace[1]==(fail?TYFZA1_LEDS_FAILED:TYFZA1_LEDS_DONE));
  assert(total==(job==HTTP_JOB_FIP?0x200000:job==HTTP_JOB_REBUILD||job==HTTP_JOB_NAND_SCRUB?0:buffer_size));
 }
 job_kind=HTTP_JOB_STORAGE;result=0;
 for(int write=0;write<2;write++){
  storage_request.operation=write?HTTP_STORAGE_OP_WRITE:HTTP_STORAGE_OP_READ;calls=0;
  assert(!tyf_http_run_job());assert(trace[0]==(write?TYFZA1_LEDS_BUSY:TYFZA1_LEDS_IDLE));
 }
 job_kind=HTTP_JOB_TYF_RESTORE;strcpy(tyf_restore_operation,"restore-chunk");
 restore=(struct tyfza1_restore_status){true,0x200000,0x10000000};calls=0;
 assert(!tyf_http_run_job() && trace[0]==TYFZA1_LEDS_BUSY && trace[1]==TYFZA1_LEDS_BUSY);
 assert(done==0x200000+buffer_size && total==0x10000000);
 post_state.connection=&restore;post_state.kind=HTTP_POST_UPLOAD;calls=0;
 tyf_http_leds_poll();assert(!calls && polls==1); /* Whole restore stays unsafe between chunks. */
 post_state.connection=NULL;tyf_http_leds_poll();assert(!calls);
 result=-5;calls=0;assert(tyf_http_run_job()==-5 && trace[1]==TYFZA1_LEDS_FAILED);
 result=0;clear_restore=1;strcpy(tyf_restore_operation,"restore-finish");calls=0;
 assert(!tyf_http_run_job() && trace[1]==TYFZA1_LEDS_DONE && !restore.active);
 post_state.connection=&restore;calls=0;tyf_http_leds_poll();assert(trace[0]==TYFZA1_LEDS_UPLOAD);
 post_state.connection=NULL;tyf_http_leds_poll();assert(trace[1]==TYFZA1_LEDS_IDLE);
 puts("HTTP flash/read/error/upload/whole-restore LED transitions passed");
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'test.c').write_text(code)
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                            str(path / 'test.c'), '-o', str(path / 'test')], check=True)
            subprocess.run([str(path / 'test')], check=True, timeout=5)


if __name__ == '__main__':
    unittest.main()
