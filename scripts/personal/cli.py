"""bin/personal: builds, releases, and sync for the CrossInk + freeink-sdk forks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .proc import PersonalError
from .project import Project

ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='bin/personal', description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('setup', help='verify remotes and set git config for the fork pair')
    sub.add_parser('status', help='topics, lifecycle, and drift for both forks')
    sub.add_parser('sync', help='merge both upstreams, build, then push')
    sub.add_parser('release', help='build and publish the next OTA release')
    flash = sub.add_parser('flash', help='USB-flash the personal (or debug) build')
    flash.add_argument('--debug', action='store_true', help='flash x4-pro-personal-debug instead')
    sub.add_parser('monitor', help='serial monitor, saved under device-logs/')
    sub.add_parser('logs', help='copy SD logs from a mounted USB Drive volume')
    return parser


def dispatch(project: Project, args) -> None:
    if args.command == 'release':
        from . import release
        release.release(project)
        return
    if args.command in ('flash', 'monitor', 'logs'):
        from . import device
        if args.command == 'flash':
            device.flash(project, debug=args.debug)
        elif args.command == 'monitor':
            device.monitor(project)
        else:
            device.pull_logs(project)
        return
    if args.command == 'status':
        from . import status
        status.status(project)
        return
    if args.command == 'sync':
        from . import sync
        sync.sync(project)
        return
    if args.command == 'setup':
        from . import setup_cmd
        setup_cmd.setup(project)
        return
    raise PersonalError(f'`{args.command}` is not implemented yet')


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        dispatch(Project(ROOT), args)
    except PersonalError as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0
