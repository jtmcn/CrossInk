"""Subprocess seam; tests substitute a fake Runner."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


class PersonalError(Exception):
    """A refusal or failure whose message is shown to the user as-is."""


@dataclass
class Result:
    returncode: int
    stdout: str = ''
    stderr: str = ''


class Runner:
    def run(self, argv, cwd=None, env=None, check=True, stream=False) -> Result:
        argv = [str(a) for a in argv]
        full_env = {**os.environ, **env} if env else None
        if stream:
            result = Result(subprocess.call(argv, cwd=cwd, env=full_env))
        else:
            proc = subprocess.run(argv, cwd=cwd, env=full_env, capture_output=True, text=True)
            result = Result(proc.returncode, proc.stdout, proc.stderr)
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            message = f"`{' '.join(argv)}` failed (exit {result.returncode})"
            raise PersonalError(f'{message}: {detail}' if detail else message)
        return result
