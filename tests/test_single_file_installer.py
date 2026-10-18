#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the packaged shell installer with a harmless flasher at the I/O boundary."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from package_installer import package


class SingleFileInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.log = self.directory / 'flasher.log'
        self.backup = Path('/tmp') / ('tyfza1-wrapper-backup-' + uuid.uuid4().hex)
        self.addCleanup(lambda: self.backup.unlink(missing_ok=True))
        (self.directory / 'tyfza1-flash-uboot').write_text(
            '#!/bin/sh\nset -eu\nprintf "%s\\n" "$0" "$@" > "$TYFZA1_TEST_LOG"\n'
            'if [ "$#" -eq 1 ]; then printf backup > "$TYFZA1_TEST_BACKUP"; fi\n'
            'exit "$TYFZA1_TEST_RESULT"\n')
        (self.directory / 'tyfza1-uboot-universal.bin').write_bytes(b'test loader')
        self.installer = package(self.directory)
        commands = self.directory / 'commands'
        commands.mkdir()
        (commands / 'id').write_text('#!/bin/sh\nprintf "%s\\n" "$TYFZA1_TEST_UID"\n')
        (commands / 'id').chmod(0o755)
        self.env = dict(os.environ, PATH=str(commands)+':'+os.environ['PATH'],
                        TYFZA1_TEST_LOG=str(self.log), TYFZA1_TEST_BACKUP=str(self.backup),
                        TYFZA1_TEST_RESULT='0', TYFZA1_TEST_UID='0')

    def run_installer(self, *args):
        return subprocess.run(['sh', str(self.installer), *args], cwd=self.directory,
                              env=self.env, capture_output=True, text=True)

    def assert_extracted_files_removed(self):
        executable = Path(self.log.read_text().splitlines()[0])
        self.assertFalse(executable.parent.exists())

    def test_one_command_invokes_flasher_and_preserves_backup(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.log.read_text().splitlines()
        self.assertEqual(len(args), 2)
        self.assertEqual(Path(args[1]).name, 'tyfza1-uboot-universal.bin')
        self.assertEqual(self.backup.read_bytes(), b'backup')
        self.assert_extracted_files_removed()

    def test_readonly_check_passes_relative_backup_as_absolute_path(self):
        backup = self.directory / 'stock.bin'
        backup.touch()
        result = self.run_installer('--check', 'stock.bin')
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.log.read_text().splitlines()
        self.assertEqual(args[1], '--check')
        self.assertEqual(args[-1], str(backup))
        self.assertFalse(self.backup.exists())
        self.assert_extracted_files_removed()

    def test_corruption_rejected_before_executing_flasher(self):
        data = bytearray(self.installer.read_bytes()); data[-8] ^= 1
        self.installer.write_bytes(data)
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum failed', result.stderr)
        self.assertFalse(self.log.exists())

    def test_backend_failure_is_returned_and_extraction_is_cleaned(self):
        self.env['TYFZA1_TEST_RESULT'] = '7'
        self.assertEqual(self.run_installer().returncode, 7)
        self.assertTrue(self.backup.exists())
        self.assert_extracted_files_removed()

    def test_nonroot_write_is_rejected(self):
        self.env['TYFZA1_TEST_UID'] = '1000'
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('as root', result.stderr)
        self.assertFalse(self.log.exists())

    def test_unknown_options_do_not_execute_flasher(self):
        result = self.run_installer('--invalid')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Usage:', result.stderr)
        self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
