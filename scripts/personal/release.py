"""Build and publish a personal OTA release on the CrossInk fork."""

from __future__ import annotations

import shlex
import tempfile

from . import versioning
from .proc import PersonalError
from .project import APP, ARTIFACT, PERSONAL_ENV, SDK, SDK_PATH, Project


def _require(condition, message):
    if not condition:
        raise PersonalError(message)


def check_guards(p: Project) -> list[str]:
    app, sdk = p.spec(APP), p.spec(SDK)
    branch = p.git(APP, 'rev-parse', '--abbrev-ref', 'HEAD')
    _require(branch == app.integration, f'release runs on `{app.integration}`, not `{branch}`')
    dirty = p.git(APP, 'status', '--porcelain', '--untracked-files=no')
    _require(not dirty, f'CrossInk has uncommitted changes (a moved {SDK_PATH} checkout counts):\n{dirty}')
    sdk_dirty = p.git(SDK, 'status', '--porcelain', '--untracked-files=no')
    _require(not sdk_dirty, f'{SDK_PATH} has uncommitted changes:\n{sdk_dirty}')

    p.git(APP, 'fetch', '--quiet', app.fork_remote)
    fork_ref = f'{app.fork_remote}/{app.integration}'
    _require(p.git_ok(APP, 'rev-parse', '--verify', '--quiet', fork_ref)
             and p.git(APP, 'rev-parse', 'HEAD') == p.git(APP, 'rev-parse', fork_ref),
             f'`{app.integration}` differs from `{fork_ref}`; push or pull first')

    pin = p.pinned_sdk()
    p.git(SDK, 'fetch', '--quiet', sdk.fork_remote)
    sdk_ref = f'{sdk.fork_remote}/{sdk.integration}'
    _require(p.git_ok(SDK, 'merge-base', '--is-ancestor', pin, sdk_ref),
             f'pinned SDK commit {pin[:10]} is not on `{sdk_ref}`; push the SDK first')
    _require(p.runner.run(['gh', 'auth', 'status'], check=False).returncode == 0,
             '`gh auth status` failed; run `gh auth login`')

    warnings = []
    for repo, rev in ((APP, 'HEAD'), (SDK, pin)):
        spec = p.spec(repo)
        p.git(repo, 'fetch', '--quiet', spec.upstream_remote)
        behind = int(p.git(repo, 'rev-list', '--count', f'{rev}..{p.upstream_main(repo)}'))
        if behind:
            warnings.append(f'{spec.name} is {behind} commit(s) behind upstream; consider `bin/personal sync`')
    return warnings


def release_notes(p: Project, pin: str, previous_tag) -> str:
    span = [f'{previous_tag}..HEAD'] if previous_tag else ['-n', '30', 'HEAD']
    merges = p.git(APP, 'log', '--merges', '--first-parent', '--format=- %s', *span)
    delta = p.git(SDK, 'diff', '--stat', p.upstream_main(SDK), pin)
    return '\n'.join([
        '## CrossInk merges', merges or '- (none since the previous release)', '',
        f'## freeink-sdk `{pin[:10]}` fork delta vs upstream', '```', delta or '(none)', '```', '',
    ])


def release(p: Project, out=print) -> str:
    for warning in check_guards(p):
        out(f'warning: {warning}')
    app = p.spec(APP)
    p.git(APP, 'fetch', '--quiet', '--tags', app.fork_remote)
    base = versioning.base_version(p.root)
    tags = p.git(APP, 'tag', '--list', 'v*').splitlines()
    n = versioning.next_build_number(tags, base)
    tag = versioning.release_tag(base, n)
    previous = versioning.latest_release_tag(tags)
    pin = p.pinned_sdk()

    out(f'Building {tag} ({PERSONAL_ENV}) ...')
    p.runner.run(['pio', 'run', '-e', PERSONAL_ENV], cwd=p.root,
                 env={'CROSSINK_PERSONAL_VERSION': f'{base}.{n}'}, stream=True)
    artifact = p.root / ARTIFACT
    _require(artifact.is_file(), f'build finished but {ARTIFACT} is missing')

    p.git(APP, 'tag', tag)
    p.git(APP, 'push', '--quiet', app.fork_remote, tag)
    with tempfile.NamedTemporaryFile('w', prefix='personal-notes-', suffix='.md', delete=False) as notes:
        notes.write(release_notes(p, pin, previous))
    command = ['gh', 'release', 'create', tag, str(artifact), '--repo', app.fork_slug,
               '--title', tag, '--notes-file', notes.name, '--latest']
    result = p.runner.run(command, check=False)
    if result.returncode != 0:
        raise PersonalError(f'tag {tag} is pushed but the upload failed: {result.stderr.strip()}\n'
                            f'retry with:\n  {shlex.join(command)}')
    out(f'Published {tag}. On the reader: Settings > Check for updates.')
    return tag
