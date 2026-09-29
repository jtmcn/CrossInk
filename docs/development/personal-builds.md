# Personal Builds

Personal X4 Pro firmware is built from two forks that are operated as one
project: `jtmcn/CrossInk` and its `freeink-sdk` submodule `jtmcn/freeink-sdk`.
Design: `docs/superpowers/specs/2026-09-28-personal-builds-design.md`.

## Branches

| | CrossInk | freeink-sdk |
| --- | --- | --- |
| Upstream remote | `upstream` (uxjulia) | `origin` (Free-Ink) |
| Fork remote | `origin` | `fork` |
| Integration branch | `personal` | `crossink` |
| Topics | `joel/*` from upstream `main` | `joel/*` from the upstream commit `crossink` last merged |

Integration branches only advance by merging. A change with SDK and app
halves pairs an SDK topic (merged into `crossink`) with a CrossInk topic whose
commit pins that merge; `bin/personal status` derives the pairing.

## How the fork is maintained

Personal builds come only from `personal`, never from fork `main` or the top of
a PR stack. Fork `main` mirrors upstream exactly; `sync` fast-forwards it and
refuses if it has diverged, so never merge anything into it.

1. **Change:** branch a topic from `upstream/main` (SDK: from the upstream
   commit `crossink` last merged), commit, then
   `git switch personal && git merge --no-ff joel/<topic>` and push.
2. **Ship:** `bin/personal release`; the reader picks it up via Check for updates.
3. **Stay current:** `bin/personal sync` now and then.
4. **Upstream it:** open the PR from the topic branch to uxjulia/CrossInk or
   Free-Ink/freeink-sdk. Fork PRs are not part of the flow; when upstream merges,
   `status` marks the topic retired and prints the delete command.

## Commands

| Command | Does |
| --- | --- |
| `bin/personal setup` | Verifies remotes (adding missing ones); sets `push.recurseSubmodules=check`, `diff.submodule=log`, `status.submoduleSummary=true`. |
| `bin/personal status` | Drift, fork delta, topic pairs, and each topic's upstream-PR state with the next action. |
| `bin/personal sync` | Requires `personal` checked out with both trees clean and no merge in progress; mirrors the fork `main`s, merges upstream into `crossink` then `personal`, repins, builds x4-pro-personal/default/simulator, then pushes the SDK before CrossInk; refuses if `crossink` lacks upstream's or `personal`'s pinned SDK commit or a local integration branch is behind its fork, and stops on conflicts (rerun after committing). |
| `bin/personal release` | Guards (on `personal`, clean, pushed, SDK pin on `fork/crossink`, `gh` authed), builds `v<base>.<N>`, tags, publishes a GitHub release with `firmware-x4-pro.bin` and its symbols as `firmware-x4-pro-<tag>.elf.gz`. |
| `bin/personal flash [--debug]` | USB-flashes the personal build (release version when HEAD is tagged) or `x4-pro-personal-debug` (debug build that still OTAs from the fork). Wake the reader first. |
| `bin/personal monitor` | Serial monitor saved to `device-logs/serial-*.log`. |
| `bin/personal logs` | With the reader in USB Drive mode, copies `.crosspoint/logs/*` and `crash_report.txt` into `device-logs/<timestamp>/`. |

## Release runbook

1. `git switch personal`; merge any finished topic with `git merge --no-ff joel/<topic>`; push.
2. `bin/personal status` — check warnings.
3. `bin/personal release`.
4. On the reader: Settings > Check for updates. Settings > System shows `<base>.<N>-x4-pro` and the SHA.

After a debug session (`bin/personal flash --debug`), Check for updates offers
the latest release, because debug builds report `<base>.0`.

## When a fork change can go

`status` marks a topic **retired** once its upstream PR is merged and the
integration branch contains that merge. Delete the branch with the printed
command. A topic is **superseded** when upstream delivers the same effect another
way (its PR usually shows as closed, and a sync conflict where you keep
upstream's side is the cue); only you can declare that, so delete it by hand.
When the SDK fork delta is empty, point `.gitmodules` back at Free-Ink and pin
an upstream commit.

## SD logs

The personal build writes `/.crosspoint/logs/log.txt` (rotated to `log.1.txt`
at 512 KB). Each boot starts with `=== boot <version> sha=… reset=… ===`;
watchdog, panic, and brownout resets also include the last RTC-retained lines.
Nothing is written while USB Drive owns the card, and lines logged during a
USB Drive session are lost because leaving USB Drive restarts the reader.

## Decoding a crash

After a panic the reader writes `/crash_report.txt` with a backtrace. Match
its `CrossInk version` to a release, then decode with that release's symbols:

```bash
gh release download v1.6.0.2 -R jtmcn/CrossInk -p '*.elf.gz' && gunzip firmware-x4-pro-v1.6.0.2.elf.gz
ADDR2LINE=$(find ~/.platformio/packages -name xtensa-esp32s3-elf-addr2line -type f | head -1)
"$ADDR2LINE" -pfiaC -e firmware-x4-pro-v1.6.0.2.elf 0x4037EBAB 0x4037E568 ...   # the report's stack trace
```

`PS` interrupt level 6 in the exception registers means a debug exception,
usually the end-of-stack watchpoint: a task stack overflow at the deepest frame.
