import gzip
import unittest
from pathlib import Path

from personal import release
from personal.proc import PersonalError, Result
from personal.project import ARTIFACT, Project
from personal.tests.fakes import ToolFake
from personal.tests.gitfixture import Fixture, git


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)
        self.tools = ToolFake(artifact=self.fx.root / ARTIFACT)
        self.p = Project(self.fx.root, self.tools)

    def assertRefuses(self, fragment):
        with self.assertRaises(PersonalError) as ctx:
            release.check_guards(self.p)
        self.assertIn(fragment, str(ctx.exception))

    def test_refuses_off_personal(self):
        git(self.fx.root, 'checkout', '-q', '-b', 'joel/elsewhere')
        self.assertRefuses('release runs on `personal`')

    def test_refuses_dirty_tree(self):
        (self.fx.root / 'platformio.ini').write_text('[crossink]\nversion = 1.6.0\n# edit\n')
        self.assertRefuses('uncommitted changes')

    def test_refuses_unpushed_personal(self):
        self.fx.commit(self.fx.root, 'local.txt', 'x\n', 'local only')
        self.assertRefuses('differs from `origin/personal`')

    def test_refuses_pin_missing_from_fork_crossink(self):
        self.fx.commit(self.fx.sdk, 'unpushed.txt', 'x\n', 'sdk: unpushed')
        git(self.fx.root, 'add', 'freeink-sdk')
        git(self.fx.root, 'commit', '-q', '-m', 'pin unpushed sdk')
        git(self.fx.root, 'push', '-q', 'origin', 'personal')
        self.assertRefuses('is not on `fork/crossink`')

    def test_refuses_without_gh_auth(self):
        self.tools.gh_responses[('gh', 'auth', 'status')] = Result(1, '', 'not logged in')
        self.assertRefuses('gh auth status')

    def test_warns_when_behind_upstream(self):
        self.fx.advance_app_upstream('new.txt', 'x\n')
        warnings = release.check_guards(self.p)
        self.assertTrue(any('CrossInk' in w and 'behind upstream' in w for w in warnings))

    def test_release_builds_tags_and_publishes(self):
        tag = release.release(self.p, out=lambda *_: None)
        self.assertEqual(tag, 'v1.6.0.1')
        pio_calls = [c for c in self.tools.calls if c['argv'][0] == 'pio']
        self.assertEqual([c['argv'] for c in pio_calls], [['pio', 'run', '-e', 'x4-pro-personal']])
        self.assertEqual(pio_calls[0]['env'], {'CROSSINK_PERSONAL_VERSION': '1.6.0.1'})
        self.assertIn('v1.6.0.1', git(self.fx.app_fork, 'tag', '--list'))
        create = [c for c in self.tools.tool_calls('gh') if c[1:3] == ['release', 'create']][0]
        self.assertIn('--latest', create)
        self.assertNotIn('--prerelease', create)
        self.assertNotIn('--draft', create)
        self.assertIn('jtmcn/CrossInk', create)
        elf = [a for a in create if a.endswith('firmware-x4-pro-v1.6.0.1.elf.gz')]
        self.assertEqual(len(elf), 1)
        self.assertEqual(gzip.decompress(Path(elf[0]).read_bytes()), b'\x7fELF symbols')
        self.assertEqual(release.release(self.p, out=lambda *_: None), 'v1.6.0.2')

    def test_release_counts_tags_only_on_fork(self):
        other = self.fx.tmp / 'other-clone'
        git(self.fx.tmp, 'clone', '-q', self.fx.app_fork, other)
        git(other, 'tag', 'v1.6.0.3', 'origin/personal')
        git(other, 'push', '-q', 'origin', 'v1.6.0.3')
        self.assertEqual(release.release(self.p, out=lambda *_: None), 'v1.6.0.4')

    def test_upload_failure_keeps_tag_and_prints_retry(self):
        self.tools.gh_responses[('gh', 'release', 'create')] = Result(1, '', 'upload broke')
        with self.assertRaises(PersonalError) as ctx:
            release.release(self.p, out=lambda *_: None)
        self.assertIn('retry with', str(ctx.exception))
        self.assertIn('gh release create v1.6.0.1', str(ctx.exception))
        self.assertIn('v1.6.0.1', git(self.fx.app_fork, 'tag', '--list'))

    def test_notes_include_merges_and_sdk_delta(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        self.fx.advance_sdk_upstream('upstream-only.txt', 'x\n')
        git(self.fx.sdk, 'fetch', '-q', 'origin')
        notes = release.release_notes(self.p, self.p.pinned_sdk(), None)
        self.assertIn("Merge branch 'joel/app-a' into personal", notes)
        self.assertIn('a.txt', notes)
        self.assertNotIn('upstream-only.txt', notes)


if __name__ == '__main__':
    unittest.main()
