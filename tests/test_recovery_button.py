#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check recovery wiring in the built image and execute the production callback."""
import ctypes as C
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RecoveryButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (ROOT/'overlay/board/realtek/tyfza1/tyfza1.c').read_text()
        start = source.index('static int tyfza1_recovery_button(')
        body = source[start:source.index('EVENT_SPY_SIMPLE(', start)]
        work = ROOT/'build/recovery-button-test';work.mkdir(parents=True, exist_ok=True)
        prelude = r'''#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
static bool reset_requested;
static int button_state, http_result, http_calls, dhcp, policy=1, boot_disabled, lights;
static int tyfza1_reset_held(void) {return button_state;}
static void tyfza1_boot_leds(void) {lights++;}
static int env_get_yesno(const char *name) {(void)name;return policy;}
static int env_set(const char *name,const char *value) {
 if(!strcmp(name,"bootcmd") && !value[0])boot_disabled=1;return 0;
}
static int uboot_httpd_start(bool with_dhcp) {
 http_calls++;dhcp=with_dhcp;return http_result;
}
'''
        tail = r'''
int test_button(int latched, int state, int result) {
 reset_requested=latched;button_state=state;http_result=result;http_calls=0;dhcp=0;boot_disabled=lights=0;
 return tyfza1_recovery_button();
}
int test_http_calls(void) { return http_calls; }
int test_dhcp(void) { return dhcp; }
void test_policy(int value) {policy=value;}
int test_boot_disabled(void) {return boot_disabled;}
int test_lights(void) {return lights;}
'''
        path=work/'button.c';path.write_text(prelude+body+tail)
        library=work/'button.so'
        subprocess.run(['cc','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
                        str(path),'-o',str(library)],check=True)
        cls.lib=C.CDLL(str(library));cls.lib.test_button.argtypes=[C.c_int,C.c_int,C.c_int]

    def test_event_framework_survives_kconfig_resolution(self):
        config=(ROOT/'build/tyfza1/.config').read_text().splitlines()
        self.assertIn('CONFIG_EVENT=y',config)

    def test_compiled_button_has_required_keycode_and_active_low_pin(self):
        dtb=ROOT/'build/tyfza1/u-boot.dtb'
        def get(prop):
            text=subprocess.check_output(['fdtget','-t','x',str(dtb),'/buttons/reset',prop],text=True)
            return [int(v,16) for v in text.split()]
        self.assertEqual(get('linux,code'),[0x198])
        self.assertEqual(get('gpios')[-2:],[8,1])

    def test_pressed_button_starts_recovery_with_dhcp(self):
        self.assertEqual(self.lib.test_button(0,1,0),0)
        self.assertEqual(self.lib.test_http_calls(),1)
        self.assertEqual(self.lib.test_dhcp(),1)

    def test_released_button_continues_normal_boot(self):
        self.assertEqual(self.lib.test_button(0,0,0),0)
        self.assertEqual(self.lib.test_http_calls(),0)

    def test_early_press_is_kept_after_button_release(self):
        self.assertEqual(self.lib.test_button(1,0,0),0)
        self.assertEqual(self.lib.test_http_calls(),1)
        self.assertEqual(self.lib.test_boot_disabled(),1)

    def test_static_policy_is_honored(self):
        self.lib.test_policy(0)
        self.assertEqual(self.lib.test_button(1,0,0),0)
        self.assertEqual(self.lib.test_dhcp(),0)
        self.lib.test_policy(1)

    def test_startup_lights_run_on_normal_and_recovery_boot(self):
        for state in (0,1):
            self.lib.test_button(0,state,0)
            self.assertEqual(self.lib.test_lights(),1)

    def test_http_failure_is_reported(self):
        self.assertEqual(self.lib.test_button(0,1,-110),0)
        self.assertEqual(self.lib.test_http_calls(),1)
        self.assertEqual(self.lib.test_boot_disabled(),1)


if __name__=='__main__':unittest.main()
