"""Runner fakes: FakeRunner answers every command; ToolFake runs real git but fakes pio and gh."""

from __future__ import annotations

from personal.proc import PersonalError, Result, Runner


class FakeRunner(Runner):
    def __init__(self, responses=None, default=Result(0)):
        self.responses = dict(responses or {})
        self.default = default
        self.calls = []

    def run(self, argv, cwd=None, env=None, check=True, stream=False):
        argv = [str(a) for a in argv]
        self.calls.append({'argv': argv, 'cwd': cwd, 'env': env})
        result = self.default
        for prefix, response in self.responses.items():
            if tuple(argv[: len(prefix)]) == prefix:
                result = response
                break
        if check and result.returncode != 0:
            raise PersonalError(f"`{' '.join(argv)}` failed (exit {result.returncode})")
        return result


class ToolFake(Runner):
    """Real git; pio succeeds (optionally writing the artifact) unless its env is in fail_envs; gh uses gh_responses."""

    def __init__(self, fail_envs=(), gh_responses=None, artifact=None):
        self.fail_envs = set(fail_envs)
        self.gh_responses = dict(gh_responses or {})
        self.artifact = artifact
        self.calls = []

    def run(self, argv, cwd=None, env=None, check=True, stream=False):
        argv = [str(a) for a in argv]
        if argv[0] == 'pio':
            self.calls.append({'argv': argv, 'env': env})
            failed = any(e in argv for e in self.fail_envs)
            if not failed and self.artifact is not None:
                self.artifact.parent.mkdir(parents=True, exist_ok=True)
                self.artifact.write_bytes(b'firmware')
                (self.artifact.parent / 'firmware.elf').write_bytes(b'\x7fELF symbols')
            result = Result(1 if failed else 0)
        elif argv[0] == 'gh':
            self.calls.append({'argv': argv, 'env': env})
            result = Result(0, '[]')
            for prefix, response in self.gh_responses.items():
                if tuple(argv[: len(prefix)]) == prefix:
                    result = response
                    break
        else:
            return super().run(argv, cwd=cwd, env=env, check=check, stream=False)
        if check and result.returncode != 0:
            raise PersonalError(f"`{' '.join(argv)}` failed (exit {result.returncode})")
        return result

    def tool_calls(self, tool):
        return [c['argv'] for c in self.calls if c['argv'][0] == tool]
