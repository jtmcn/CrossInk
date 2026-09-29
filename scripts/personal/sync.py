"""Catch both forks up with their upstreams, build, then push SDK before CrossInk."""

from __future__ import annotations

from .proc import PersonalError
from .project import APP, SDK, SDK_PATH, SYNC_BUILD_ENVS, Project


def _require_no_merge_in_progress(p: Project, repo: str) -> None:
    if p.git_ok(repo, 'rev-parse', '--verify', '--quiet', 'MERGE_HEAD'):
        raise PersonalError(f'{p.spec(repo).name} has a merge in progress in {p.path(repo)}; '
                            'finish it with `git commit` (or abort it), then rerun `bin/personal sync`')


def _require_clean(p: Project) -> None:
    # A moved SDK checkout is expected when resuming, so the gitlink line is allowed.
    app_dirty = [line for line in p.git(APP, 'status', '--porcelain', '--untracked-files=no').splitlines()
                 if not line.endswith(f' {SDK_PATH}')]
    if app_dirty:
        raise PersonalError('CrossInk has uncommitted changes:\n' + '\n'.join(app_dirty))
    sdk_dirty = p.git(SDK, 'status', '--porcelain', '--untracked-files=no')
    if sdk_dirty:
        raise PersonalError(f'{SDK_PATH} has uncommitted changes:\n{sdk_dirty}')


def _resolve_gitlink_conflict(p: Project) -> None:
    theirs = p.git(APP, 'rev-parse', f'MERGE_HEAD:{SDK_PATH}')
    ours = p.git(SDK, 'rev-parse', 'HEAD')
    if not p.git_ok(SDK, 'merge-base', '--is-ancestor', theirs, ours):
        raise PersonalError(f'upstream CrossInk pins SDK {theirs[:10]}, which `crossink` does not contain; '
                            f'merge it into crossink, then `git add {SDK_PATH} && git commit` and rerun sync')
    p.git(APP, 'add', SDK_PATH)
    p.git(APP, 'commit', '--quiet', '--no-edit')


def _merge_upstream(p: Project, repo: str, out) -> None:
    spec, upstream = p.spec(repo), p.upstream_main(repo)
    if p.git_ok(repo, 'merge-base', '--is-ancestor', upstream, 'HEAD'):
        out(f'{spec.name}: `{spec.integration}` already contains {upstream}')
        return
    merged = p.runner.run(['git', 'merge', '--no-ff', '--no-edit', upstream], cwd=p.path(repo), check=False)
    if merged.returncode == 0:
        return
    conflicted = p.git(repo, 'diff', '--name-only', '--diff-filter=U').splitlines()
    if repo == APP and conflicted == [SDK_PATH]:
        _resolve_gitlink_conflict(p)
        return
    files = '\n'.join(f'  {name}' for name in conflicted) or '  (see `git status`)'
    raise PersonalError(f'{spec.name}: merging {upstream} into `{spec.integration}` conflicted in:\n{files}\n'
                        f'resolve in {p.path(repo)}, `git commit`, then rerun `bin/personal sync`')


def sync(p: Project, out=print) -> None:
    app, sdk = p.spec(APP), p.spec(SDK)
    branch = p.git(APP, 'rev-parse', '--abbrev-ref', 'HEAD')
    if branch != app.integration:
        raise PersonalError(f'sync runs on `{app.integration}`, not `{branch}`')
    for repo in (APP, SDK):
        _require_no_merge_in_progress(p, repo)
    _require_clean(p)

    for repo in (SDK, APP):
        spec = p.spec(repo)
        p.git(repo, 'fetch', '--quiet', spec.upstream_remote)
        p.git(repo, 'fetch', '--quiet', spec.fork_remote)
        # Fast-forward only: a diverged fork main fails here instead of being overwritten.
        p.git(repo, 'push', '--quiet', spec.fork_remote, f'{p.upstream_main(repo)}:refs/heads/main')
        if repo == SDK:
            p.git(SDK, 'checkout', '--quiet', sdk.integration)
        _merge_upstream(p, repo, out)

    tip = p.git(SDK, 'rev-parse', 'HEAD')
    if p.pinned_sdk() != tip:
        p.git(APP, 'add', SDK_PATH)
        p.git(APP, 'commit', '--quiet', '-m', f'chore: sync freeink-sdk crossink to {tip[:10]}')

    for env in SYNC_BUILD_ENVS:
        out(f'Building {env} ...')
        p.runner.run(['pio', 'run', '-e', env], cwd=p.root, stream=True)

    p.git(SDK, 'push', '--quiet', sdk.fork_remote, sdk.integration)
    p.git(APP, 'push', '--quiet', app.fork_remote, app.integration)
    from . import status
    status.status(p, out=out)
