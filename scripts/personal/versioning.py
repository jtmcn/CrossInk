"""Personal release numbering: v<crossink.version>.<N>."""

from __future__ import annotations

import configparser
import re
from pathlib import Path

from .proc import PersonalError

TAG_RE = re.compile(r'^v(\d+\.\d+\.\d+)\.(\d+)$')
BASE_RE = re.compile(r'^\d+\.\d+\.\d+$')


def base_version(root: Path) -> str:
    config = configparser.ConfigParser()
    config.read([root / 'platformio.ini', root / 'platformio.local.ini'])
    if not config.has_option('crossink', 'version'):
        raise PersonalError('no [crossink] version in platformio.ini')
    base = config.get('crossink', 'version').strip()
    if not BASE_RE.match(base):
        raise PersonalError(f'[crossink] version `{base}` is not MAJOR.MINOR.PATCH; OTA compares numeric segments')
    return base


def _parsed(tags):
    for tag in tags:
        match = TAG_RE.match(tag.strip())
        if match:
            yield tag.strip(), match.group(1), int(match.group(2))


def next_build_number(tags, base: str) -> int:
    return max((n for _, b, n in _parsed(tags) if b == base), default=0) + 1


def release_tag(base: str, n: int) -> str:
    return f'v{base}.{n}'


def latest_release_tag(tags):
    ranked = [(tuple(int(x) for x in b.split('.')), n, tag) for tag, b, n in _parsed(tags)]
    return max(ranked)[2] if ranked else None


def version_at_head(tags_at_head, base: str):
    numbers = [n for _, b, n in _parsed(tags_at_head) if b == base]
    return f'{base}.{max(numbers)}' if numbers else None
