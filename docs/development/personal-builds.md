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

## Commands

| Command | Does |
| --- | --- |
| `bin/personal setup` | Verifies remotes; sets `push.recurseSubmodules=check`, `diff.submodule=log`, `status.submoduleSummary=true`. |
| `bin/personal status` | Drift, fork delta, topic pairs, and each topic's upstream-PR state with the next action. |
| `bin/personal sync` | Mirrors both fork `main`s, merges upstream into `crossink` then `personal`, repins the SDK, builds `x4-pro-personal`/`default`/`simulator`, then pushes SDK before CrossInk. Stops on conflicts; rerun after committing the resolution. |
| `bin/personal release` | Guards (on `personal`, clean, pushed, SDK pin on `fork/crossink`, `gh` authed), builds `v<base>.<N>`, tags, publishes a GitHub release with `firmware-x4-pro.bin`. |
| `bin/personal flash [--debug]` | USB-flashes the personal build (release version when HEAD is tagged) or `x4-pro-debug`. Wake the reader first. |
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
command. When the SDK fork delta is empty, point `.gitmodules` back at
Free-Ink and pin an upstream commit.

## SD logs

The personal build writes `/.crosspoint/logs/log.txt` (rotated to `log.1.txt`
at 512 KB). Each boot starts with `=== boot <version> sha=… reset=… ===`;
watchdog, panic, and brownout resets also include the last RTC-retained lines.
Logging pauses while USB Drive owns the card.
