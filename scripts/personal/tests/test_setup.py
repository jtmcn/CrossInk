import unittest
from pathlib import Path

from personal import setup_cmd
from personal.proc import PersonalError, Result
from personal.project import Project
from personal.tests.fakes import FakeRunner

APP_REMOTES = {'upstream': 'git@github.com:uxjulia/CrossInk.git', 'origin': 'git@github.com:jtmcn/CrossInk.git'}
SDK_REMOTES = {'origin': 'https://github.com/Free-Ink/freeink-sdk.git',
               'fork': 'https://github.com/jtmcn/freeink-sdk.git'}


class CwdRunner(FakeRunner):
    def __init__(self, app, sdk):
        super().__init__()
        self.tables = {'app': dict(app), 'sdk': dict(sdk)}

    def run(self, argv, cwd=None, env=None, check=True, stream=False):
        argv = [str(a) for a in argv]
        if argv[:3] != ['git', 'remote', 'get-url']:
            return super().run(argv, cwd, env, check, stream)
        self.calls.append({'argv': argv, 'cwd': cwd, 'env': env})
        table = self.tables['sdk' if str(cwd).endswith('freeink-sdk') else 'app']
        url = table.get(argv[3])
        result = Result(0, url + '\n') if url else Result(2, '', 'No such remote')
        if check and result.returncode:
            raise PersonalError('missing remote')
        return result


def project(app=APP_REMOTES, sdk=SDK_REMOTES):
    runner = CwdRunner(app, sdk)
    return Project(Path('/r'), runner), runner


class SetupTest(unittest.TestCase):
    def test_sets_git_config_in_crossink_only(self):
        p, runner = project()
        setup_cmd.setup(p, out=lambda *_: None)
        configs = [(c['argv'][2:], c['cwd']) for c in runner.calls if c['argv'][:2] == ['git', 'config']]
        self.assertIn((['push.recurseSubmodules', 'check'], Path('/r')), configs)
        self.assertIn((['diff.submodule', 'log'], Path('/r')), configs)
        self.assertIn((['status.submoduleSummary', 'true'], Path('/r')), configs)
        self.assertNotIn('submodule.recurse', [argv[0] for argv, _ in configs])

    def test_adds_missing_remote(self):
        p, runner = project(sdk={'origin': SDK_REMOTES['origin']})
        setup_cmd.setup(p, out=lambda *_: None)
        self.assertIn(['git', 'remote', 'add', 'fork', 'https://github.com/jtmcn/freeink-sdk.git'],
                      [c['argv'] for c in runner.calls])

    def test_refuses_wrong_remote(self):
        p, _ = project(app={**APP_REMOTES, 'upstream': 'git@github.com:someone/CrossInk.git'})
        with self.assertRaises(PersonalError) as ctx:
            setup_cmd.setup(p, out=lambda *_: None)
        self.assertIn('uxjulia/CrossInk', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
