"""Combined status for the CrossInk + freeink-sdk fork pair."""

from __future__ import annotations

from . import topics
from .project import APP, SDK, Project


def _indent(text: str) -> list[str]:
    return ['    ' + line for line in text.splitlines()]


def _has_ref(p, repo, ref):
    return p.git_ok(repo, 'rev-parse', '--verify', '--quiet', ref)


def repo_lines(p: Project, repo: str) -> list[str]:
    spec, up = p.spec(repo), p.upstream_main(repo)
    lines = [f'== {spec.name} ==']
    ahead, behind = p.git(repo, 'rev-list', '--left-right', '--count', f'{spec.fork_remote}/main...{up}').split()
    drift = '' if ahead == behind == '0' else '  <- fork main should mirror upstream; `sync` fixes'
    lines.append(f'fork main vs upstream: {ahead} ahead, {behind} behind{drift}')
    if not _has_ref(p, repo, f'refs/heads/{spec.integration}'):
        lines.append(f'`{spec.integration}` branch missing')
        return lines
    lines.append(f'`{spec.integration}` behind upstream: '
                 f'{p.git(repo, "rev-list", "--count", f"{spec.integration}..{up}")} commit(s)')
    delta = p.git(repo, 'diff', '--stat', f'{up}...{spec.integration}')
    lines.append('fork delta:' if delta else 'fork delta: none')
    lines += _indent(delta)
    for topic in topics.local_topics(p, repo):
        notes = []
        if not p.git_ok(repo, 'merge-base', '--is-ancestor', topic, spec.integration):
            notes.append(f'not merged into {spec.integration}')
        remote = f'{spec.fork_remote}/{topic}'
        if not _has_ref(p, repo, remote) or p.git(repo, 'rev-parse', topic) != p.git(repo, 'rev-parse', remote):
            notes.append('not pushed')
        if notes:
            lines.append(f'  {topic}: ' + ', '.join(notes))
    return lines


def sdk_pin_lines(p: Project) -> list[str]:
    pin = p.pinned_sdk()
    if not pin:
        return ['pin: CrossInk HEAD has no freeink-sdk gitlink']
    tip = p.git(SDK, 'rev-parse', 'crossink', check=False)
    lines = [f'pin: matches crossink tip ({pin[:10]})' if pin == tip
             else f'pin: {pin[:10]} differs from crossink tip {tip[:10]}']
    if not p.git(SDK, 'diff', '--stat', f'{p.upstream_main(SDK)}...{pin}'):
        lines.append('SDK fork no longer needed: repin to Free-Ink and restore .gitmodules')
    return lines


def topic_lines(p: Project) -> list[str]:
    pairing = topics.derive_pairs(p)
    sdk_to_app = {s: a for a, sdks in pairing.pairs.items() for s in sdks}
    lines = ['== Topics ==']
    for repo in (APP, SDK):
        spec = p.spec(repo)
        for topic in topics.local_topics(p, repo):
            pr = topics.find_pr(p, repo, topic)
            oid = ((pr or {}).get('mergeCommit') or {}).get('oid')
            merged = bool(oid) and p.git_ok(repo, 'merge-base', '--is-ancestor', oid, spec.integration)
            state = topics.classify(pr, merged)
            pair = ', '.join(pairing.pairs.get(topic, [])) if repo == APP else sdk_to_app.get(topic, '')
            pair_text = f'<-> {pair}' if pair else ''
            lines.append(f'{spec.name:<12}{topic:<40}{state.value:<30}{pair_text:<44}{topics.ACTIONS[state]}')
            if state is topics.State.RETIRED:
                lines.append(f'    git -C {p.path(repo)} branch -D {topic} && '
                             f'git -C {p.path(repo)} push {spec.fork_remote} --delete {topic}')
    for commit in pairing.unpaired_bumps:
        lines.append(f'unpaired gitlink bump {commit[:10]}: pinned SDK commit is not a crossink topic merge')
    return lines


def report(p: Project, fetch: bool = True) -> list[str]:
    if fetch:
        for repo in (APP, SDK):
            spec = p.spec(repo)
            p.git(repo, 'fetch', '--quiet', spec.upstream_remote)
            p.git(repo, 'fetch', '--quiet', spec.fork_remote)
    return repo_lines(p, APP) + [''] + repo_lines(p, SDK) + sdk_pin_lines(p) + [''] + topic_lines(p)


def status(p: Project, out=print) -> None:
    for line in report(p):
        out(line)
