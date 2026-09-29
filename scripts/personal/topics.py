"""Topic pairing across the two forks and upstream-PR lifecycle."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum

from .proc import PersonalError
from .project import APP, SDK, SDK_PATH, TOPIC_PREFIX, Project

MERGE_SUBJECT = re.compile(r"^Merge branch '([^']+)' into crossink$")


class State(Enum):
    FORK_ONLY = 'fork-only, no PR'
    PR_OPEN = 'PR open'
    MERGED_UNSYNCED = 'merged upstream, not synced'
    RETIRED = 'retired'
    CLOSED = 'PR closed unmerged'


ACTIONS = {
    State.FORK_ONLY: 'open an upstream PR, or keep as fork-only',
    State.PR_OPEN: 'wait for review',
    State.MERGED_UNSYNCED: 'run `bin/personal sync`',
    State.RETIRED: 'delete the topic branch',
    State.CLOSED: 'rework, or keep as fork-only',
}


def classify(pr, merge_in_integration: bool) -> State:
    if pr is None:
        return State.FORK_ONLY
    if pr.get('state') == 'OPEN':
        return State.PR_OPEN
    if pr.get('state') == 'MERGED':
        return State.RETIRED if merge_in_integration else State.MERGED_UNSYNCED
    return State.CLOSED


def find_pr(p: Project, repo: str, topic: str):
    spec = p.spec(repo)
    owner = spec.fork_slug.split('/')[0]
    result = p.runner.run(['gh', 'pr', 'list', '-R', spec.upstream_slug, '--head', topic, '--state', 'all',
                           '--json', 'number,state,mergeCommit,headRepositoryOwner,url'], check=False)
    if result.returncode != 0:
        raise PersonalError(f'could not query PRs for {topic}: {result.stderr.strip()}')
    prs = [pr for pr in json.loads(result.stdout or '[]')
           if (pr.get('headRepositoryOwner') or {}).get('login') == owner]
    return prs[0] if prs else None


def local_topics(p: Project, repo: str) -> list[str]:
    out = p.git(repo, 'for-each-ref', '--format=%(refname:short)', f'refs/heads/{TOPIC_PREFIX}')
    return [line for line in out.splitlines() if line]


@dataclass
class Pairing:
    pairs: dict = field(default_factory=dict)
    unpaired_bumps: list = field(default_factory=list)


def derive_pairs(p: Project) -> Pairing:
    upstream = p.upstream_main(APP)
    names = local_topics(p, APP)
    depth = {t: int(p.git(APP, 'rev-list', '--count', f'{upstream}..{t}')) for t in names}
    owner = {}
    # Deepest first, so shallower (lower-in-stack) topics claim shared bump commits last.
    for topic in sorted(names, key=lambda t: depth[t], reverse=True):
        for commit in p.git(APP, 'log', '--format=%H', f'{upstream}..{topic}', '--', SDK_PATH).splitlines():
            owner[commit] = topic

    pairing = Pairing({t: [] for t in names})
    for commit, topic in owner.items():
        pin = p.pinned_sdk(commit)
        if not pin or p.git_ok(SDK, 'merge-base', '--is-ancestor', pin, p.upstream_main(SDK)):
            continue
        match = MERGE_SUBJECT.match(p.git(SDK, 'log', '-1', '--format=%s', pin, check=False))
        if match is None:
            pairing.unpaired_bumps.append(commit)
        elif match.group(1) not in pairing.pairs[topic]:
            pairing.pairs[topic].append(match.group(1))
    return pairing
