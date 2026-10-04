import json
import unittest

from personal import status
from personal.proc import Result
from personal.project import Project
from personal.tests.fakes import ToolFake
from personal.tests.gitfixture import Fixture, git


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)
        self.tools = ToolFake()
        self.p = Project(self.fx.root, self.tools)

    def text(self):
        return '\n'.join(status.report(self.p))

    def test_reports_pairs_states_and_delta(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        out = self.text()
        self.assertIn('joel/app-a', out)
        self.assertIn('<-> joel/sdk-a', out)
        self.assertIn('fork-only, no PR', out)
        self.assertIn('a.txt', out)
        self.assertIn('pin: matches crossink tip', out)

    def test_retired_topic_prints_delete_command(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        merged = git(self.fx.sdk, 'rev-parse', 'crossink')
        pr = [{'number': 3, 'state': 'MERGED', 'headRepositoryOwner': {'login': 'jtmcn'},
               'mergeCommit': {'oid': merged}}]
        self.tools.gh_responses[('gh', 'pr', 'list', '-R', 'Free-Ink/freeink-sdk', '--head', 'joel/sdk-a')] = \
            Result(0, json.dumps(pr))
        out = self.text()
        self.assertIn('retired', out)
        self.assertIn('branch -D joel/sdk-a', out)

    def test_fork_main_drift_is_flagged(self):
        self.fx.advance_sdk_upstream('up.txt', 'x\n')
        self.assertIn('0 ahead, 1 behind', self.text())

    def test_unpushed_and_unmerged_topics_are_flagged(self):
        git(self.fx.root, 'checkout', '-q', '-b', 'joel/local', 'upstream/main')
        self.fx.commit(self.fx.root, 'local.txt', 'x\n', 'feat: local only')
        git(self.fx.root, 'checkout', '-q', 'personal')
        out = self.text()
        self.assertIn('joel/local: not merged into personal, not pushed', out)

    def test_empty_sdk_delta_says_fork_not_needed(self):
        self.assertIn('SDK fork no longer needed', self.text())

    def test_fork_delta_excludes_upstream_only_changes(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        self.fx.advance_sdk_upstream('upstream-only.txt', 'x\n')
        out = self.text()
        self.assertIn('a.txt', out)
        self.assertNotIn('upstream-only.txt', out)
        self.assertNotIn('SDK fork no longer needed', out)

    def test_status_reports_missing_integration_branch(self):
        git(self.fx.root, 'checkout', '-q', '--detach')
        git(self.fx.root, 'branch', '-D', 'personal')
        self.assertIn('`personal` branch missing', self.text())

    def test_upstream_pinning_unpublished_sdk_commit_does_not_break_fetch(self):
        self.fx.advance_app_upstream('up.txt', 'x\n', pin_sdk='63cf9ba4d9812e1bf0985c050c27f0abb357cd66')
        self.assertIn('pin: matches crossink tip', self.text())


if __name__ == '__main__':
    unittest.main()
