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
#define BUTTON_ON 1
struct udevice { int unused; };
static struct udevice button;
static int lookup_result, button_state, http_result, http_calls, dhcp;
static int button_get_by_label(const char *label, struct udevice **out) {
 if (strcmp(label,"reset")) return -EINVAL;
 *out=&button;return lookup_result;
}
static int button_get_state(struct udevice *dev) { (void)dev;return button_state; }
static int uboot_httpd_start(bool with_dhcp) {
 http_calls++;dhcp=with_dhcp;return http_result;
}
'''
        tail = r'''
int test_button(int lookup, int state, int result) {
 lookup_result=lookup;button_state=state;http_result=result;http_calls=0;dhcp=0;
 return tyfza1_recovery_button();
}
int test_http_calls(void) { return http_calls; }
int test_dhcp(void) { return dhcp; }
'''
        path=work/'button.c';path.write_text(prelude+body+tail)
        library=work/'button.so'
        subprocess.run(['cc','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror',
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

    def test_unavailable_button_continues_normal_boot(self):
        self.assertEqual(self.lib.test_button(-19,0,0),0)
        self.assertEqual(self.lib.test_http_calls(),0)

    def test_read_error_continues_normal_boot(self):
        self.assertEqual(self.lib.test_button(0,-5,0),0)
        self.assertEqual(self.lib.test_http_calls(),0)

    def test_http_failure_is_reported(self):
        self.assertEqual(self.lib.test_button(0,1,-110),-110)
        self.assertEqual(self.lib.test_http_calls(),1)


if __name__=='__main__':unittest.main()
