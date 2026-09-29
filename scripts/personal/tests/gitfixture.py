"""Throwaway upstream/fork bare repos for both projects plus a local CrossInk clone with the SDK submodule."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

GIT_ENV = {
    'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.com',
    'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.com',
    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
    'GIT_CONFIG_COUNT': '2',
    'GIT_CONFIG_KEY_0': 'protocol.file.allow', 'GIT_CONFIG_VALUE_0': 'always',
    'GIT_CONFIG_KEY_1': 'init.defaultBranch', 'GIT_CONFIG_VALUE_1': 'main',
}


def git(cwd, *args) -> str:
    return subprocess.run(['git', *map(str, args)], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


class Fixture:
    def __init__(self):
        self._saved_env = dict(os.environ)
        os.environ.update(GIT_ENV)
        self._tmp = tempfile.TemporaryDirectory(prefix='personal-fixture-')
        t = Path(self._tmp.name)
        self.tmp = t
        self.sdk_upstream, self.sdk_fork = t / 'sdk-up.git', t / 'sdk-fork.git'
        self.app_upstream, self.app_fork = t / 'app-up.git', t / 'app-fork.git'
        for bare in (self.sdk_upstream, self.sdk_fork, self.app_upstream, self.app_fork):
            git(t, 'init', '-q', '--bare', bare)

        seed = t / 'sdk-seed'
        git(t, 'init', '-q', seed)
        self.commit(seed, 'lib.txt', 'v1\n', 'sdk: initial')
        git(seed, 'push', '-q', self.sdk_upstream, 'main')
        git(seed, 'push', '-q', self.sdk_fork, 'main')

        app_seed = t / 'app-seed'
        git(t, 'init', '-q', app_seed)
        (app_seed / 'platformio.ini').write_text('[crossink]\nversion = 1.6.0\n')
        git(app_seed, 'submodule', 'add', '-q', self.sdk_fork, 'freeink-sdk')
        git(app_seed, 'add', '-A')
        git(app_seed, 'commit', '-q', '-m', 'app: initial')
        git(app_seed, 'push', '-q', self.app_upstream, 'main')
        git(app_seed, 'push', '-q', self.app_fork, 'main')

        self.root = t / 'CrossInk'
        git(t, 'clone', '-q', '--recurse-submodules', self.app_fork, self.root)
        git(self.root, 'remote', 'add', 'upstream', self.app_upstream)
        git(self.root, 'fetch', '-q', 'upstream')
        self.sdk = self.root / 'freeink-sdk'
        git(self.sdk, 'remote', 'rename', 'origin', 'fork')
        git(self.sdk, 'remote', 'add', 'origin', self.sdk_upstream)
        git(self.sdk, 'fetch', '-q', 'origin')
        git(self.sdk, 'checkout', '-q', '-b', 'crossink', 'origin/main')
        git(self.sdk, 'push', '-q', 'fork', 'crossink')
        git(self.root, 'checkout', '-q', '-b', 'personal', 'upstream/main')
        git(self.root, 'push', '-q', 'origin', 'personal')

    @staticmethod
    def commit(repo, name, text, message):
        (Path(repo) / name).write_text(text)
        git(repo, 'add', name)
        git(repo, 'commit', '-q', '-m', message)

    def add_sdk_topic(self, name, filename, text='topic\n'):
        git(self.sdk, 'checkout', '-q', '-b', name, 'origin/main')
        self.commit(self.sdk, filename, text, f'sdk: {name}')
        git(self.sdk, 'push', '-q', 'fork', name)
        git(self.sdk, 'checkout', '-q', 'crossink')
        git(self.sdk, 'merge', '-q', '--no-ff', name, '-m', f"Merge branch '{name}' into crossink")
        git(self.sdk, 'push', '-q', 'fork', 'crossink')

    def add_app_topic(self, name, base='upstream/main', bump_sdk=False, merge=True):
        git(self.root, 'checkout', '-q', '-b', name, base)
        self.commit(self.root, name.replace('/', '-') + '.txt', 'x\n', f'feat: {name}')
        if bump_sdk:
            git(self.root, 'add', 'freeink-sdk')
            git(self.root, 'commit', '-q', '-m', f'chore: pin sdk for {name}')
        git(self.root, 'push', '-q', 'origin', name)
        git(self.root, 'checkout', '-q', 'personal')
        if merge:
            git(self.root, 'merge', '-q', '--no-ff', name, '-m', f"Merge branch '{name}' into personal")
            git(self.root, 'push', '-q', 'origin', 'personal')

    def _work_clone(self, bare, name):
        work = self.tmp / name
        if not work.exists():
            git(self.tmp, 'clone', '-q', bare, work)
        git(work, 'pull', '-q', 'origin', 'main')
        return work

    def advance_sdk_upstream(self, filename, text):
        work = self._work_clone(self.sdk_upstream, 'sdk-up-work')
        self.commit(work, filename, text, f'upstream sdk: {filename}')
        git(work, 'push', '-q', 'origin', 'main')
        return git(work, 'rev-parse', 'HEAD')

    def advance_app_upstream(self, filename, text, pin_sdk=None):
        work = self._work_clone(self.app_upstream, 'app-up-work')
        self.commit(work, filename, text, f'upstream app: {filename}')
        if pin_sdk:
            git(work, 'update-index', '--cacheinfo', f'160000,{pin_sdk},freeink-sdk')
            git(work, 'commit', '-q', '-m', 'upstream app: bump sdk')
        git(work, 'push', '-q', 'origin', 'main')

    @staticmethod
    def remote_sha(bare, ref):
        return git(bare, 'rev-parse', ref)

    def cleanup(self):
        self._tmp.cleanup()
        os.environ.clear()
        os.environ.update(self._saved_env)
