import tempfile
import unittest
from pathlib import Path

from personal import versioning
from personal.proc import PersonalError


class VersioningTest(unittest.TestCase):
    def test_first_build_of_a_base_is_one(self):
        self.assertEqual(versioning.next_build_number(['v1.5.0.9', 'v1.6.0'], '1.6.0'), 1)

    def test_next_build_increments_highest(self):
        tags = ['v1.6.0.1', 'v1.6.0.10', 'v1.6.0.2']
        self.assertEqual(versioning.next_build_number(tags, '1.6.0'), 11)

    def test_base_change_resets(self):
        self.assertEqual(versioning.next_build_number(['v1.6.0.4'], '1.7.0'), 1)

    def test_release_tag(self):
        self.assertEqual(versioning.release_tag('1.6.0', 3), 'v1.6.0.3')

    def test_latest_release_tag_orders_numerically(self):
        tags = ['v1.6.0.9', 'v1.6.0.10', 'v1.5.9.99', 'v1.6.0', 'junk']
        self.assertEqual(versioning.latest_release_tag(tags), 'v1.6.0.10')
        self.assertIsNone(versioning.latest_release_tag(['v1.6.0']))

    def test_version_at_head(self):
        self.assertEqual(versioning.version_at_head(['v1.6.0.2', 'v1.6.0.3'], '1.6.0'), '1.6.0.3')
        self.assertIsNone(versioning.version_at_head(['v1.5.0.3'], '1.6.0'))

    def test_base_version_reads_ini_and_local_override(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'platformio.ini').write_text('[crossink]\nversion = 1.6.0\n')
            self.assertEqual(versioning.base_version(root), '1.6.0')
            (root / 'platformio.local.ini').write_text('[crossink]\nversion = 1.7.0\n')
            self.assertEqual(versioning.base_version(root), '1.7.0')

    def test_base_version_rejects_non_semver(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'platformio.ini').write_text('[crossink]\nversion = 1.6\n')
            with self.assertRaises(PersonalError):
                versioning.base_version(root)


if __name__ == '__main__':
    unittest.main()
