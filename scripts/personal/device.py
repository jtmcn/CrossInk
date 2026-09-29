"""USB flashing, serial capture, and SD log retrieval for the X4 Pro."""

from __future__ import annotations

import glob
import platform
import shlex
import shutil
from datetime import datetime
from pathlib import Path

from . import versioning
from .proc import PersonalError
from .project import APP, DEBUG_ENV, PERSONAL_ENV, Project

WAKE_MESSAGE = ('no /dev/cu.usbmodem* port found: wake the reader (deep sleep turns USB off), '
                'check the cable, and retry')


def list_ports() -> list[str]:
    return glob.glob('/dev/cu.usbmodem*') + glob.glob('/dev/ttyACM*')


def select_port(candidates, choose=input) -> str:
    # macOS auto-detect can pick the Bluetooth port; only USB CDC ports are valid.
    ports = sorted(c for c in candidates if 'usbmodem' in c or 'ttyACM' in c)
    if not ports:
        raise PersonalError(WAKE_MESSAGE)
    if len(ports) == 1:
        return ports[0]
    listing = '\n'.join(f'  {i}) {port}' for i, port in enumerate(ports, 1))
    answer = choose(f'Several ports:\n{listing}\nPick one [1-{len(ports)}]: ').strip()
    if not answer.isdigit() or not 1 <= int(answer) <= len(ports):
        raise PersonalError(f'no port selected ({answer!r})')
    return ports[int(answer) - 1]


def flash(p: Project, debug=False, ports=None, choose=input) -> None:
    port = select_port(list_ports() if ports is None else ports, choose)
    env = None
    if not debug:
        tags = p.git(APP, 'tag', '--points-at', 'HEAD').splitlines()
        version = versioning.version_at_head(tags, versioning.base_version(p.root))
        env = {'CROSSINK_PERSONAL_VERSION': version} if version else None
    target = DEBUG_ENV if debug else PERSONAL_ENV
    p.runner.run(['pio', 'run', '-e', target, '-t', 'upload', '--upload-port', port], cwd=p.root, env=env,
                 stream=True)


def monitor_command(port: str, logfile: Path, system: str) -> list[str]:
    inner = ['pio', 'device', 'monitor', '-p', port, '-b', '115200', '-f', 'time']
    if system == 'Darwin':
        return ['script', '-q', str(logfile), *inner]
    return ['script', '-q', '-c', shlex.join(inner), str(logfile)]


def monitor(p: Project, ports=None, choose=input) -> None:
    port = select_port(list_ports() if ports is None else ports, choose)
    logs = p.root / 'device-logs'
    logs.mkdir(exist_ok=True)
    logfile = logs / f'serial-{datetime.now():%Y%m%d-%H%M%S}.log'
    print(f'Saving to {logfile}. Ctrl-C to stop.')
    p.runner.run(monitor_command(port, logfile, platform.system()), cwd=p.root, stream=True, check=False)


def find_log_volume(volumes_root: Path) -> Path:
    readers = [v for v in sorted(volumes_root.iterdir()) if (v / '.crosspoint').is_dir()] \
        if volumes_root.is_dir() else []
    if not readers:
        raise PersonalError(f'no reader volume under {volumes_root}: start USB Drive on the reader first')
    if len(readers) > 1:
        raise PersonalError('several reader volumes mounted: ' + ', '.join(str(r) for r in readers))
    return readers[0]


def pull_logs(p: Project, volumes_root: Path = Path('/Volumes'), now=None) -> Path:
    volume = find_log_volume(volumes_root)
    sources = sorted((volume / '.crosspoint' / 'logs').glob('*.txt'))
    crash = volume / 'crash_report.txt'
    if crash.is_file():
        sources.append(crash)
    if not sources:
        raise PersonalError(f'{volume} has no logs yet (.crosspoint/logs is empty)')
    dest = p.root / 'device-logs' / f'{(now or datetime.now()):%Y%m%d-%H%M%S}'
    dest.mkdir(parents=True)
    for source in sources:
        shutil.copy2(source, dest / source.name)
    print(f'Copied {len(sources)} file(s) to {dest}')
    return dest
