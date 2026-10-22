#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Version stays two-component; build provenance describes the actual tree."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from prepare import build_identity


class BuildIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.root / 'VERSION').write_text('1.1\n')
        (self.root / '.gitignore').write_text('build/\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'baseline')
        self.commit = self.git('rev-parse', '--short=7', 'HEAD').strip()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True)

    def test_clean(self):
        self.assertEqual(build_identity(self.root), ('1.1', self.commit))

    def test_modified_and_staged_files(self):
        (self.root / 'VERSION').write_text('1.2\n')
        self.assertEqual(build_identity(self.root), ('1.2', self.commit + '-dirty'))
        self.git('add', 'VERSION')
        self.assertEqual(build_identity(self.root), ('1.2', self.commit + '-dirty'))

    def test_untracked_source_marks_dirty(self):
        (self.root / 'new.c').write_text('/* new source */\n')
        self.assertEqual(build_identity(self.root), ('1.1', self.commit + '-dirty'))

    def test_ignored_build_files_do_not_mark_dirty(self):
        (self.root / 'build').mkdir()
        (self.root / 'build/u-boot.bin').write_bytes(b'output')
        self.assertEqual(build_identity(self.root), ('1.1', self.commit))

    def test_archive_does_not_inherit_parent_repository_commit(self):
        archive = self.root / 'archive'
        archive.mkdir()
        (archive / 'VERSION').write_text('1.1\n')
        self.assertEqual(build_identity(archive), ('1.1', ''))

    def test_archive_without_git(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory)
            (archive / 'VERSION').write_text('1.1\n')
            self.assertEqual(build_identity(archive), ('1.1', ''))

    def test_three_component_version_is_rejected(self):
        (self.root / 'VERSION').write_text('1.1.1\n')
        with self.assertRaises(ValueError):
            build_identity(self.root)


if __name__ == '__main__':
    unittest.main()
