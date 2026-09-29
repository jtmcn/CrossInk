import unittest

from personal import sync
from personal.proc import PersonalError
from personal.project import Project
from personal.tests.fakes import ToolFake
from personal.tests.gitfixture import Fixture, git


def quiet(*_):
    pass


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)
        self.tools = ToolFake()
        self.p = Project(self.fx.root, self.tools)

    def fork_refs(self):
        return (self.fx.remote_sha(self.fx.sdk_fork, 'crossink'), self.fx.remote_sha(self.fx.app_fork, 'personal'))

    def test_sync_merges_both_upstreams_builds_and_pushes(self):
        sdk_up = self.fx.advance_sdk_upstream('up.txt', 'x\n')
        self.fx.advance_app_upstream('app-up.txt', 'x\n')
        sync.sync(self.p, out=quiet)
        fork_crossink, fork_personal = self.fork_refs()
        git(self.fx.sdk_fork, 'merge-base', '--is-ancestor', sdk_up, fork_crossink)
        self.assertEqual(self.fx.remote_sha(self.fx.sdk_fork, 'main'), sdk_up)
        self.assertEqual(self.fx.remote_sha(self.fx.app_fork, 'main'), self.fx.remote_sha(self.fx.app_upstream, 'main'))
        pinned = git(self.fx.app_fork, 'ls-tree', fork_personal, 'freeink-sdk').split()[2]
        self.assertEqual(pinned, fork_crossink)
        self.assertEqual([c[3] for c in self.tools.tool_calls('pio')], ['x4-pro-personal', 'default', 'simulator'])

    def test_sync_build_failure_pushes_nothing(self):
        self.fx.advance_sdk_upstream('up.txt', 'x\n')
        before = self.fork_refs()
        self.tools.fail_envs.add('default')
        with self.assertRaises(PersonalError):
            sync.sync(self.p, out=quiet)
        self.assertEqual(self.fork_refs(), before)

    def test_sync_sdk_conflict_stops_before_push(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'lib.txt', 'ours\n')
        self.fx.advance_sdk_upstream('lib.txt', 'theirs\n')
        before = self.fork_refs()
        with self.assertRaises(PersonalError) as ctx:
            sync.sync(self.p, out=quiet)
        self.assertIn('lib.txt', str(ctx.exception))
        self.assertIn('rerun `bin/personal sync`', str(ctx.exception))
        self.assertEqual(self.fork_refs(), before)
        self.assertEqual(self.tools.tool_calls('pio'), [])

    def test_sync_resumes_after_resolved_sdk_conflict(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'lib.txt', 'ours\n')
        self.fx.advance_sdk_upstream('lib.txt', 'theirs\n')
        with self.assertRaises(PersonalError):
            sync.sync(self.p, out=quiet)
        (self.fx.sdk / 'lib.txt').write_text('resolved\n')
        git(self.fx.sdk, 'add', 'lib.txt')
        git(self.fx.sdk, 'commit', '-q', '--no-edit')
        sync.sync(self.p, out=quiet)
        fork_crossink, fork_personal = self.fork_refs()
        self.assertEqual(git(self.fx.app_fork, 'ls-tree', fork_personal, 'freeink-sdk').split()[2], fork_crossink)

    def test_sync_resolves_upstream_gitlink_bump(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        sdk_up = self.fx.advance_sdk_upstream('up.txt', 'x\n')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        self.fx.advance_app_upstream('app-up.txt', 'x\n', pin_sdk=sdk_up)
        sync.sync(self.p, out=quiet)
        fork_crossink, fork_personal = self.fork_refs()
        self.assertEqual(git(self.fx.app_fork, 'ls-tree', fork_personal, 'freeink-sdk').split()[2], fork_crossink)

    def test_sync_refuses_off_personal(self):
        git(self.fx.root, 'checkout', '-q', '-b', 'joel/elsewhere')
        with self.assertRaises(PersonalError) as ctx:
            sync.sync(self.p, out=quiet)
        self.assertIn('sync runs on `personal`', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
