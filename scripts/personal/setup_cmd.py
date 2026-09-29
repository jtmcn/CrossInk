"""Wire the CrossInk + freeink-sdk checkouts so they behave as one project."""

from __future__ import annotations

from .proc import PersonalError
from .project import APP, SDK, Project

# submodule.recurse is deliberately absent: it detaches the SDK checkout on every branch switch.
GIT_CONFIG = (
    ('push.recurseSubmodules', 'check'),
    ('diff.submodule', 'log'),
    ('status.submoduleSummary', 'true'),
)


def setup(p: Project, out=print) -> None:
    for repo in (APP, SDK):
        spec = p.spec(repo)
        for remote, slug in ((spec.upstream_remote, spec.upstream_slug), (spec.fork_remote, spec.fork_slug)):
            url = p.git(repo, 'remote', 'get-url', remote, check=False)
            if not url:
                p.git(repo, 'remote', 'add', remote, f'https://github.com/{slug}.git')
                out(f'{spec.name}: added remote `{remote}` -> {slug}')
            elif slug.lower() not in url.lower():
                raise PersonalError(f'{spec.name} remote `{remote}` is {url}, expected {slug}')
    for key, value in GIT_CONFIG:
        p.git(APP, 'config', key, value)
    out('git config set: ' + ', '.join(f'{k}={v}' for k, v in GIT_CONFIG))
