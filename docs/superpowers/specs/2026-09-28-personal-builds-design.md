# Personal Builds, OTA Installs, and SD Logging — Design

Date: 2026-09-28
Status: approved design, pending implementation plan

## Goal

A repeatable system for building and installing Joel's personal X4 Pro
firmware from the `jtmcn/CrossInk` + `jtmcn/freeink-sdk` forks, where:

- every installed build is identifiable and reproducible from a tag;
- daily builds install over Wi-Fi through the reader's existing OTA flow;
- the daily build records logs to the SD card during normal use, so problems
  can be diagnosed after the fact without a USB cable attached;
- desk-side debug builds remain one command away and never strand the device;
- the two forks are operated locally as one project: one CLI, one status
  view, one sync, and git configured so they cannot drift apart silently;
- every fork-only SDK change has a visible lifecycle, so it is clear when it
  can be removed.

Non-goals: other devices (X3/X4, Sticky, X4 Classic), upstream-quality
polish, CI builds, public distribution. Only the X4 Pro is supported.

## Current State (2026-09-28)

- Release env `x4-pro` versions as `1.6.0-x4-pro` with no commit identity
  (`scripts/git_branch.py`, `get_hardware_version`); `CROSSINK_GIT_SHA` is
  injected separately and shown in Settings › System.
- `x4-pro-debug` sets `CROSSPOINT_WAIT_FOR_USB_SERIAL`, which blocks boot until
  a serial host connects — unusable for daily reading.
- OTA (`src/network/OtaUpdater.cpp`) reads `CROSSINK_OTA_RELEASE_URL`
  (default `uxjulia/CrossInk` releases/latest), matches asset
  `firmware-x4-pro.bin` or `firmware-x4-pro-*.bin`, verifies the GitHub asset
  `digest` (sha256), and compares up to four numeric version segments.
- Logs go to USB serial only. `lib/Logging` keeps a 16-line RTC ring that is
  written to `/crash_report.txt` only after a panic.
- Topic work is a stack of `joel/*` branches on `upstream/main` (`b25beb13`).
- SDK: `crossink` (`447c7a3`) = upstream `b784446` + three topics
  (`joel/x4-aa-skip-redundant-dtm1`, `joel/x4-uc8279-spi-clock-opt-in`,
  `joel/x4-aa-overlap-settle`), all pushed to the fork, none with an upstream
  PR. `crossink` is 35 upstream commits behind; fork `main` is 1 behind
  upstream (should mirror it). CrossInk `main` still points `.gitmodules` at
  Free-Ink; only the topic stack (commit `2204185e`) switches it to the fork
  with `branch = crossink`.

## Decisions

| Question | Decision |
| --- | --- |
| Install path | OTA from GitHub releases on `jtmcn/CrossInk`; USB for first install and debug sessions |
| Logging goal | Capture issues during normal use: SD log sink in the daily build |
| Build source | A `personal` integration branch |
| Build host | Local Mac, published with `gh` |
| Layout | Tracked personal layer on `personal` (approach A), minimal edits to shared files |
| Repos | CrossInk + freeink-sdk forks treated as one project locally |
| SDK change lifecycle | Derived from git + upstream PR state; no manifest file |
| First upstream catch-up | Done by the first real run of `bin/personal sync` |

## 1. Branches, Versions, Releases

### Branch model

The two repos use the same shape:

| | CrossInk (`jtmcn/CrossInk`) | SDK (`jtmcn/freeink-sdk`) |
| --- | --- | --- |
| Upstream remote | `upstream` (uxjulia) | `origin` (Free-Ink) |
| Fork remote | `origin` | `fork` |
| Fork `main` | mirrors `upstream/main` exactly | mirrors `origin/main` exactly |
| Integration branch | `personal` | `crossink` |
| Topics | `joel/*`, based on upstream `main` | `joel/*`, based on the upstream commit `crossink` last merged |

- `personal` = `upstream/main` + `--no-ff` merges of each `joel/*` topic +
  the personal-layer commits (this design lands as topic
  `joel/personal-build-system`). Stacked topics are merged by their top branch.
- `personal` carries the fork `.gitmodules` (URL `jtmcn/freeink-sdk`,
  `branch = crossink`) and pins a `crossink` commit.
- Both integration branches only advance by merging, so every pinned or
  released commit stays reachable.
- A change with SDK and app halves is a *paired topic*: an SDK topic merged
  into `crossink`, plus a CrossInk topic whose gitlink-bump commit pins that
  merge. Pairing is derived, not declared (Section 1b).

### Versioning

- Release tag: `v<crossink.version>.<N>`, e.g. `v1.6.0.7`.
- `N` = 1 + the highest existing `v<base>.*` tag for the current
  `[crossink] version`; it restarts at 1 when the base version changes.
- The firmware reports `<base>.<N>-x4-pro` (e.g. `1.6.0.7-x4-pro`).
  `OtaUpdater::compareVersions` parses segments `1,6,0,7` and stops at `-`.
- Debug and ad-hoc builds (`x4-pro-debug`, plain `x4-pro`) parse as
  `<base>.0`, so Check for Updates offers the latest personal release and
  returns the device to the daily build with no special step.

### `x4-pro-personal` environment

Added to `platformio.ini` on the personal layer; extends `env:x4-pro` so it
gets its own `.pio/build/x4-pro-personal` directory (switching between it and
stock `x4-pro` does not force full rebuilds). Adds:

- `-DCROSSINK_OTA_RELEASE_URL=\"https://api.github.com/repos/jtmcn/CrossInk/releases/latest\"`
- `-DCROSSINK_SD_LOG`
- `-DLOG_LEVEL=2` (replacing the inherited `LOG_LEVEL=1`)
- `custom_firmware_device_type = x4-pro` so the artifact is `firmware-x4-pro.bin`.

`scripts/git_branch.py` gains a branch for `x4-pro-personal`: version is
`$CROSSINK_PERSONAL_VERSION` + `-x4-pro` when set, otherwise `<base>.0-x4-pro`
(so local builds of the env never outrank a published release).

### `bin/personal` CLI

`bin/personal` is a thin shell wrapper around `scripts/personal.py`
(argparse subcommands, stdlib only, shells out to `git`, `pio`, `gh`). Every
command operates on both repos; there is no separate SDK command namespace.

- `setup` — idempotent local wiring for the pair:
  - verifies `freeink-sdk` remotes (`origin` = Free-Ink, `fork` = jtmcn) and
    adds any that are missing;
  - sets in the CrossInk repo: `push.recurseSubmodules=check` (refuse to push
    a CrossInk commit whose pinned SDK commit is not on a remote),
    `diff.submodule=log`, `status.submoduleSummary=true`;
  - deliberately does not set `submodule.recurse`: it would detach the SDK
    checkout from `crossink`/topic branches on every CrossInk branch switch.
- `status` — combined view of both repos (Section 1b).
- `sync` — catch both forks up with their upstreams (Section 1b).
- `release` — build and publish a daily build:
  1. Guards (each refuses with a specific message): current branch is
     `personal`; tracked tree clean (including the `freeink-sdk` gitlink
     matching the checkout); `personal` equals `origin/personal`; the pinned
     SDK commit is reachable from `fork/crossink`; `gh auth status`
     succeeds. Warns (does not refuse) when either integration branch is
     behind its upstream.
  2. Compute `N`; build `x4-pro-personal` with
     `CROSSINK_PERSONAL_VERSION=<base>.<N>`.
  3. `git tag v<base>.<N>` and push the tag.
  4. `gh release create v<base>.<N> --latest` (never `--prerelease`, never
     draft — `releases/latest` skips both) uploading
     `.pio/build/x4-pro-personal/firmware-x4-pro.bin`. Notes list the topic
     merges since the previous tag (`git log --merges --first-parent`), the
     SDK SHA, and the SDK fork delta (`git diff --stat origin/main <pin>` in
     `freeink-sdk`), so each tag records which SDK patches it shipped.
  5. If the upload fails after the tag is pushed, print the exact `gh` command
     to retry; do not delete the tag.
- `flash [--debug]` — USB flash `x4-pro-personal` (or `x4-pro-debug`). When
  HEAD carries a `v<base>.<N>` tag, the build uses that version so it is
  identical to the release; otherwise it is `<base>.0`. Port
  selection: `/dev/cu.usbmodem*` only, never Bluetooth; exactly one match is
  used, several prompt, none prints "wake the reader (deep sleep disables
  USB) and retry".
- `monitor` — `pio device monitor -f time` on the same port selection,
  recorded with `script` to `device-logs/serial-<ts>.log`.
- `logs` — copy SD logs from a mounted USB Drive volume (Section 2).

`device-logs/` is added to `.gitignore`.

Accepted trade-off: releases on `jtmcn/CrossInk` are public. Only devices
built with the fork OTA URL pull them.

## 1b. Fork Changes: Inclusion and Removal

### How a change reaches the build

SDK change → SDK topic `joel/<x>` (based on the upstream commit `crossink`
last merged) → `--no-ff` merge into `crossink` → push both to `fork` →
CrossInk topic commit bumps the gitlink to that merge → CrossInk topic merged
into `personal`. PlatformIO compiles exactly the pinned SDK commit. CrossInk
topics without SDK changes skip the SDK steps.

### Pairing (derived)

For each CrossInk commit on a topic that changes the `freeink-sdk` gitlink,
the new SDK commit is a `crossink` merge whose second parent is an SDK topic
tip; that topic is paired with the CrossInk topic. Current pairs:

| CrossInk topic | SDK topic |
| --- | --- |
| `joel/x4-aa-faster-antialiasing` | `joel/x4-aa-skip-redundant-dtm1` |
| `joel/x4pro-display-spi-20mhz` | `joel/x4-uc8279-spi-clock-opt-in` |
| `joel/x4pro-aa-overlap-settle` | `joel/x4-aa-overlap-settle` |
| `joel/x4pro-psram-threshold` | — |

No renames: pushed branch names back open fork PRs.

### Topic lifecycle (`bin/personal status`)

One row per topic in each integration branch, grouped by pair. Upstream PR
state comes from `gh pr list -R <upstream> --head <topic> --state all
--json number,state,mergeCommit` (fork PRs are ignored).

| State | Detected by | Action shown |
| --- | --- | --- |
| Fork-only, no PR | no upstream PR for that head | open upstream PR, or keep as fork-only |
| PR open | state OPEN | wait |
| Merged upstream, not synced | MERGED, merge commit not in integration branch | run `sync` |
| Retired | MERGED, integration branch contains upstream's merge | delete topic branch (command printed) |
| Closed unmerged | state CLOSED | rework, or keep as fork-only |

Below the table, per repo:

- fork delta: `git diff --stat <upstream>/main <integration>`; for the SDK,
  diffed against the pinned commit as well as the `crossink` tip;
- fork `main` drift from upstream `main` (should be zero);
- integration branch commits behind upstream;
- topics not merged into the integration branch, or not pushed;
- SDK: whether the CrossInk pin equals the `crossink` tip.

When the SDK fork delta is empty, status prints "SDK fork no longer needed:
repin to Free-Ink and restore `.gitmodules`".

Removal needs no history rewrite: once upstream contains a topic's change and
`sync` merges upstream into the integration branch, the topic contributes
nothing further; retiring it means deleting the branch.

Convention (not tooled): an SDK topic whose effect depends on a CrossInk
build flag or call site names that dependent in its commit message (e.g.
`-DFREEINK_UC8279X4_SPI_HZ` for `spi-clock-opt-in`). An unused `-D` does not
fail the build, so these are re-checked by hand when upstream reworks the area.

### `bin/personal sync`

Runs on `personal` with both trees clean. Order keeps the gitlink reachable:

1. SDK: `git fetch origin fork`; mirror `git push fork origin/main:main`.
2. SDK: on `crossink`, `git merge --no-ff origin/main`. On conflict: stop,
   print the conflicted files and the upstream commits involved, exit
   non-zero; rerunning `sync` after the merge is committed resumes.
3. CrossInk: `git fetch upstream origin`; mirror
   `git push origin upstream/main:main`; on `personal`,
   `git merge --no-ff upstream/main` (same conflict handling).
4. CrossInk: stage the new SDK gitlink and commit
   `chore: sync freeink-sdk crossink to <sha>` if it changed.
5. Build `x4-pro-personal`, `default`, `simulator`. Any failure stops before
   pushing; the local merges stay for fixing.
6. Push SDK `crossink` to `fork`, then CrossInk `personal` to `origin`
   (`push.recurseSubmodules=check` enforces the order).
7. Print `status`.

The first real run performs the pending 35-commit SDK catch-up. The known
clash (upstream `8f97375` names a variable `local` in
`FreeInkUI/include/components/media/catalog.h`, broken by PNGdec's
`#define local static` in `SleepActivity.cpp`) surfaces at step 5 and is
fixed with a CrossInk-side commit on `personal` (or a topic) before rerunning.

## 2. SD Logging

### Invariant

The logging call path never touches the SD card. `logPrintf` runs on any task,
including code holding the `HalStorage` mutex (`lib/hal/HalStorage.cpp`
`StorageLock`); an SD write from inside it could deadlock or stall rendering.
Log lines are copied to RAM; only the main loop writes them to SD, through the
normal mutex-protected `Storage` API.

### `lib/Logging` hook (only shared-library change)

- `using LogSinkFn = void (*)(const char* line, size_t len);`
- `void setLogSink(LogSinkFn sink);`
- `logPrintf` calls the sink after formatting, alongside the serial and RTC
  ring writes. A function pointer, not `std::function`. Null by default:
  builds without a registered sink behave exactly as today.

### `src/util/SdLogSink.{h,cpp}` (compiled only with `CROSSINK_SD_LOG`)

Split into a storage-free core (host-testable) and a thin SD writer:

- `LogBuffer` (core): fixed-capacity byte ring with drop-newest overflow and a
  dropped-line counter; tracks oldest-unflushed timestamp and whether an
  `ERR` line is pending; exposes `shouldFlush(nowMs, storageExclusive)` and a
  snapshot/commit pair so lines appended during a flush are preserved.
- Buffer: 16 KB, allocated once in PSRAM at init via `heap_caps_malloc(…,
  MALLOC_CAP_SPIRAM)`. On failure: one `LOG_ERR`, sink stays unregistered,
  device continues. Static storage is not used because 16 KB of internal DRAM
  is not justified for a diagnostic feature on a PSRAM device.
- Append: short `portMUX` critical section around the index update and
  `memcpy`; no allocation, no logging, no I/O.
- Flush policy (`SdLogSink::service()`, called each `loop()` iteration after the exclusive-storage early return):
  flush when an `ERR` is pending, the buffer is ≥ 50 % full, or the oldest
  unflushed line is ≥ 10 s old. Never flush while
  `activityManager.requiresExclusiveStorageLoop()` is true (USB Drive, serial
  file transfer).
- Forced flush: `SdLogSink::flushNow()` in `enterDeepSleep()` and before
  intentional restarts (see call sites below).
- Write: open `/.crosspoint/logs/log.txt` for append, write, close each flush
  (no handle held between flushes). After `[dropped N lines]` overflow, the
  marker is written before the next batch. Write failures log once per boot
  and keep the data buffered until the next attempt.
- Rotation: when `log.txt` exceeds 512 KB before a write, remove `log.1.txt`,
  rename `log.txt` → `log.1.txt`. Total footprint ≈ 1 MB.

### Boot banner and hang recovery

At `begin()` (before `HalSystem::begin()`), queue:

- `=== boot <version> sha=<CROSSINK_GIT_SHA> dirty=<0|1> reset=<reason> ===`,
  followed after settings load by a `clock <local time>` (or `clock unset`) line
- If the reset reason is task/interrupt watchdog, panic, or brownout, the
  RTC ring contents from `getLastLogs()` under a `--- last lines before
  reset ---` header. This makes hangs diagnosable: the watchdog resets the
  chip before the RAM buffer flushes, but the RTC ring survives.

Worst-case loss on abrupt reset: < 10 s of lines, mostly recovered from the
RTC ring.

### `main.cpp` call sites (unconditional; `SdLogSink.h` supplies inline no-ops without `CROSSINK_SD_LOG`)

1. `SdLogSink::begin()` before `HalSystem::begin()` in `setup()` (that call clears the
   RTC ring on non-panic boots); flushes wait for `Storage.ready()`.
2. `SdLogSink::service()` in `loop()`, after the exclusive-storage early return.
3. `SdLogSink::flushNow()` in `enterDeepSleep()` before sleep teardown.
4. `SdLogSink::flushNow()` before each intentional `ESP.restart()`:
   `silentRestart()` (`src/main.cpp`), `OtaUpdateActivity` success, and
   `SdFirmwareUpdateActivity` success.

### Verbosity

The personal build compiles `LOG_LEVEL=2`. With no USB host attached,
`if (logSerial)` already skips the serial write, so the added cost per line is
the existing `snprintf` plus one `memcpy`. If measured volume rotates the
files within a day of reading, drop to `LOG_LEVEL=1` (one flag).

### Retrieval: `bin/personal logs`

The reader enters USB Drive mode; the script finds the mounted volume that
contains `.crosspoint/` (under `/Volumes`), copies `.crosspoint/logs/*` and
`crash_report.txt` (if present) into `device-logs/<timestamp>/`, and prints
the path. The web portal is not used: it refuses dot-prefixed paths
(`CrossPointWebServer.cpp` `isProtectedPath`).

## 3. Testing and Verification

### Host tests

- `test/sd_log_sink/` (CMake/CTest, stubs pattern as in `test/memory_policy`):
  flush triggers (ERR, half full, age, suppressed while storage-exclusive),
  drop-newest overflow and marker text, rotation threshold decision, lines
  appended between snapshot and commit survive.
- `scripts/test_personal.py` (pytest): `N` computation (first, next, base
  change reset); each release guard refuses with its message; topic pairing
  from gitlink-bump commits; lifecycle state for each `gh pr` shape
  (none/open/merged-unsynced/merged-synced/closed); `sync` stops before any
  push on merge conflict or build failure. `gh`/`pio`/`git` are faked via a
  runner seam; pairing and sync ordering also run against throwaway local
  repos (a bare "upstream", a bare "fork", and a CrossInk repo with the SDK as
  a submodule) created in a temp dir.

### Builds

`pio run -e x4-pro-personal`, `x4-pro`, `default`, `simulator` all succeed.
Stock `x4-pro` ELF contains no `SdLogSink` symbols
(`nm .pio/build/x4-pro/firmware.elf | grep -c SdLogSink` = 0).

### Hardware (X4 Pro)

0. Setup and first sync: `bin/personal setup`, then `bin/personal sync`
   (the pending SDK catch-up), then `bin/personal status` shows every topic
   in a lifecycle state, zero fork-`main` drift in both repos, and the pin at
   the `crossink` tip.
1. `bin/personal release` publishes `v1.6.0.1`; first install over USB with
   `bin/personal flash` (existing firmware points OTA at uxjulia).
   Settings › System shows `1.6.0.1-x4-pro` and the SHA.
2. Read ~10 min, sleep, wake; `bin/personal logs`: a boot banner per wake,
   ERR lines present, no gaps; note KB/hour to confirm the DBG default.
3. Start USB Drive during use, eject, stop: no card corruption, logging
   resumes afterwards, no flush occurred while the host owned the card.
4. Temporary debug-only watchdog trigger: after reset, the log contains the
   `last lines before reset` block.
5. Publish `v1.6.0.2`; Check for Updates offers it, sha verifies, installs;
   Settings shows `1.6.0.2-x4-pro`.
6. `bin/personal flash --debug`; then Check for Updates offers `v1.6.0.2`.

## Documentation

- `docs/development/personal-builds.md`: branch model, commands, release
  runbook, log retrieval.
- One pointer line in `.claude/CONTEXT.md`.
- Update the `fork-firmware-setup` memory with the `personal` branch and tag
  scheme.

## Risks

- `personal` merge conflicts on upstream sync concentrate in
  `platformio.ini`, `scripts/git_branch.py`, `lib/Logging`, and `main.cpp`;
  the personal layer keeps each edit small and additive.
- `sync` pushes to both forks' `main` and integration branches. It pushes only
  after all builds pass and never force-pushes; the mirror push fails loudly
  if a fork `main` has diverged instead of overwriting it.
- Pairing derivation depends on SDK merge messages of the form
  `Merge branch '<topic>' into crossink`; `status` lists an unpaired gitlink
  bump rather than guessing.
- GitHub unauthenticated API limit (60/h per IP) is ample for manual checks.
- A mistakenly published prerelease or draft would be invisible to OTA; the
  CLI never creates either.
