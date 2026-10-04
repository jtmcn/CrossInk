"""The CrossInk + freeink-sdk fork pair, addressed as one project."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .proc import Runner

APP = 'app'
SDK = 'sdk'
SDK_PATH = 'freeink-sdk'
TOPIC_PREFIX = 'joel/'
PERSONAL_ENV = 'x4-pro-personal'
DEBUG_ENV = 'x4-pro-personal-debug'
SYNC_BUILD_ENVS = (PERSONAL_ENV, 'default', 'simulator')
ARTIFACT = Path('.pio') / 'build' / PERSONAL_ENV / 'firmware-x4-pro.bin'


@dataclass(frozen=True)
class RepoSpec:
    name: str
    upstream_remote: str
    fork_remote: str
    integration: str
    upstream_slug: str
    fork_slug: str


APP_SPEC = RepoSpec('CrossInk', 'upstream', 'origin', 'personal', 'uxjulia/CrossInk', 'jtmcn/CrossInk')
SDK_SPEC = RepoSpec('freeink-sdk', 'origin', 'fork', 'crossink', 'Free-Ink/freeink-sdk', 'jtmcn/freeink-sdk')


@dataclass
class Project:
    root: Path
    runner: Runner = field(default_factory=Runner)

    def path(self, repo: str) -> Path:
        return self.root if repo == APP else self.root / SDK_PATH

    def spec(self, repo: str) -> RepoSpec:
        return APP_SPEC if repo == APP else SDK_SPEC

    def git(self, repo: str, *args, check: bool = True) -> str:
        return self.runner.run(['git', *args], cwd=self.path(repo), check=check).stdout.strip()

    def fetch(self, repo: str, *args) -> str:
        # Callers fetch the SDK themselves; recursing fails when upstream pins an unpublished SDK commit.
        return self.git(repo, 'fetch', '--quiet', '--no-recurse-submodules', *args)

    def git_ok(self, repo: str, *args) -> bool:
        return self.runner.run(['git', *args], cwd=self.path(repo), check=False).returncode == 0

    def upstream_main(self, repo: str) -> str:
        return f'{self.spec(repo).upstream_remote}/main'

    def pinned_sdk(self, rev: str = 'HEAD') -> str:
        # ls-tree prints "160000 commit <sha>\tfreeink-sdk" for the gitlink.
        out = self.git(APP, 'ls-tree', rev, SDK_PATH, check=False)
        return out.split()[2] if out else ''
