#!/usr/bin/env python3
"""Personal-build version injection in scripts/git_branch.py."""

import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_git_branch():
    spec = importlib.util.spec_from_file_location('git_branch_under_test', ROOT / 'scripts' / 'git_branch.py')
    module = importlib.util.module_from_spec(spec)
    with mock.patch('builtins.print'):
        spec.loader.exec_module(module)
    return module


class PersonalVersionTest(unittest.TestCase):
    def test_uses_release_number_from_env(self):
        gb = load_git_branch()
        with mock.patch.dict(os.environ, {'CROSSINK_PERSONAL_VERSION': '1.6.0.7'}):
            self.assertEqual(gb.get_personal_version(str(ROOT)), '1.6.0.7-x4-pro')

    def test_local_builds_are_build_zero(self):
        gb = load_git_branch()
        env = {k: v for k, v in os.environ.items() if k != 'CROSSINK_PERSONAL_VERSION'}
        with mock.patch.dict(os.environ, env, clear=True):
            base = gb.get_crossink_version(str(ROOT))
            self.assertEqual(gb.get_personal_version(str(ROOT)), f'{base}.0-x4-pro')


if __name__ == '__main__':
    unittest.main()
