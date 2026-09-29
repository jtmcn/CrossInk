import json
import unittest

from personal import topics
from personal.proc import Result
from personal.project import APP, SDK, Project
from personal.tests.fakes import FakeRunner, ToolFake
from personal.tests.gitfixture import Fixture, git


class ClassifyTest(unittest.TestCase):
    def test_states(self):
        self.assertIs(topics.classify(None, False), topics.State.FORK_ONLY)
        self.assertIs(topics.classify({'state': 'OPEN'}, False), topics.State.PR_OPEN)
        self.assertIs(topics.classify({'state': 'MERGED'}, False), topics.State.MERGED_UNSYNCED)
        self.assertIs(topics.classify({'state': 'MERGED'}, True), topics.State.RETIRED)
        self.assertIs(topics.classify({'state': 'CLOSED'}, False), topics.State.CLOSED)

    def test_every_state_has_an_action(self):
        self.assertEqual(set(topics.ACTIONS), set(topics.State))


class FindPrTest(unittest.TestCase):
    def test_ignores_prs_from_other_owners_and_queries_upstream(self):
        prs = [{'number': 9, 'state': 'OPEN', 'headRepositoryOwner': {'login': 'someone'}},
               {'number': 7, 'state': 'MERGED', 'headRepositoryOwner': {'login': 'jtmcn'},
                'mergeCommit': {'oid': 'abc'}}]
        runner = FakeRunner({('gh', 'pr', 'list'): Result(0, json.dumps(prs))})
        pr = topics.find_pr(Project(None, runner), SDK, 'joel/x')
        self.assertEqual(pr['number'], 7)
        argv = runner.calls[0]['argv']
        self.assertIn('Free-Ink/freeink-sdk', argv)
        self.assertIn('joel/x', argv)

    def test_no_pr(self):
        runner = FakeRunner({('gh', 'pr', 'list'): Result(0, '[]')})
        self.assertIsNone(topics.find_pr(Project(None, runner), APP, 'joel/x'))


class DerivePairsTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)
        self.p = Project(self.fx.root, ToolFake())

    def test_bump_belongs_to_lowest_stacked_topic(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        self.fx.add_app_topic('joel/app-b', base='joel/app-a')
        pairing = topics.derive_pairs(self.p)
        self.assertEqual(pairing.pairs, {'joel/app-a': ['joel/sdk-a'], 'joel/app-b': []})
        self.assertEqual(pairing.unpaired_bumps, [])

    def test_pin_to_upstream_commit_is_not_a_pairing(self):
        self.fx.advance_sdk_upstream('up.txt', 'x\n')
        git(self.fx.sdk, 'fetch', '-q', 'origin')
        git(self.fx.sdk, 'checkout', '-q', 'origin/main')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        pairing = topics.derive_pairs(self.p)
        self.assertEqual(pairing.pairs, {'joel/app-a': []})
        self.assertEqual(pairing.unpaired_bumps, [])

    def test_pin_to_non_merge_commit_is_unpaired(self):
        self.fx.commit(self.fx.sdk, 'loose.txt', 'x\n', 'sdk: loose commit on crossink')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        self.assertEqual(len(topics.derive_pairs(self.p).unpaired_bumps), 1)

    def test_pin_to_topic_commit_pairs_with_that_topic(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        git(self.fx.sdk, 'checkout', '-q', 'joel/sdk-a')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        pairing = topics.derive_pairs(self.p)
        self.assertEqual(pairing.pairs, {'joel/app-a': ['joel/sdk-a']})
        self.assertEqual(pairing.unpaired_bumps, [])

    def test_pin_on_stacked_sdk_topics_pairs_with_the_lowest(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        git(self.fx.sdk, 'checkout', '-q', '-b', 'joel/sdk-b', 'joel/sdk-a')
        self.fx.commit(self.fx.sdk, 'b.txt', 'b\n', 'sdk: b on top of a')
        git(self.fx.sdk, 'checkout', '-q', 'joel/sdk-a')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        self.assertEqual(topics.derive_pairs(self.p).pairs, {'joel/app-a': ['joel/sdk-a']})


if __name__ == '__main__':
    unittest.main()
