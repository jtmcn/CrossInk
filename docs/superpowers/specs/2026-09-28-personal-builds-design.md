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
- desk-side debug builds remain one command away and never strand the device.

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

## Decisions

| Question | Decision |
| --- | --- |
| Install path | OTA from GitHub releases on `jtmcn/CrossInk`; USB for first install and debug sessions |
| Logging goal | Capture issues during normal use: SD log sink in the daily build |
| Build source | A `personal` integration branch |
| Build host | Local Mac, published with `gh` |
| Layout | Tracked personal layer on `personal` (approach A), minimal edits to shared files |

## 1. Branches, Versions, Releases

### Branch model

Mirrors the SDK's `crossink` integration branch:

- `personal` = `upstream/main` + `--no-ff` merges of each `joel/*` topic
  branch + the personal-layer commits (this design's implementation lands as
  topic `joel/personal-build-system`, merged into `personal`).
- `personal` is only ever advanced by merging, so every released commit stays
  reachable. Upstream sync = merge `upstream/main` into `personal`.
- Topic branches stay rebased on `upstream/main` and upstream-PR-shaped.

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
(argparse subcommands, stdlib only, shells out to `git`, `pio`, `gh`).

- `release` — build and publish a daily build:
  1. Guards (each refuses with a specific message): current branch is
     `personal`; tracked tree clean (including the `freeink-sdk` gitlink
     matching the checkout); `personal` equals `origin/personal`; the pinned
     SDK commit is reachable on the `fork` remote of `freeink-sdk`; `gh auth
     status` succeeds.
  2. Compute `N`; build `x4-pro-personal` with
     `CROSSINK_PERSONAL_VERSION=<base>.<N>`.
  3. `git tag v<base>.<N>` and push the tag.
  4. `gh release create v<base>.<N> --latest` (never `--prerelease`, never
     draft — `releases/latest` skips both) uploading
     `.pio/build/x4-pro-personal/firmware-x4-pro.bin`. Notes list the topic
     merges since the previous tag (`git log --merges --first-parent`) and
     the SDK SHA.
  5. If the upload fails after the tag is pushed, print the exact `gh` command
     to retry; do not delete the tag.
- `flash [--debug]` — USB flash `x4-pro-personal` (or `x4-pro-debug`). Port
  selection: `/dev/cu.usbmodem*` only, never Bluetooth; exactly one match is
  used, several prompt, none prints "wake the reader (deep sleep disables
  USB) and retry".
- `monitor` — `pio device monitor` on the same port selection with the
  `time` and `log2file` filters, output under `device-logs/serial-<ts>.log`.
- `logs` — copy SD logs from a mounted USB Drive volume (Section 2).

`device-logs/` is added to `.gitignore`.

Accepted trade-off: releases on `jtmcn/CrossInk` are public. Only devices
built with the fork OTA URL pull them.

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
- Flush policy (`SdLogSink::service()`, called each `loop()` iteration):
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

At init (after `Storage.begin()`), queue:

- `=== boot <version> sha=<CROSSINK_GIT_SHA><dirty?> reset=<reason> time=<RTC time or "unset"> ===`
- If the reset reason is task/interrupt watchdog, panic, or brownout, the
  RTC ring contents from `getLastLogs()` under a `--- last lines before
  reset ---` header. This makes hangs diagnosable: the watchdog resets the
  chip before the RAM buffer flushes, but the RTC ring survives.

Worst-case loss on abrupt reset: < 10 s of lines, mostly recovered from the
RTC ring.

### `main.cpp` call sites (all `#ifdef CROSSINK_SD_LOG`)

1. `SdLogSink::init()` after storage is mounted in `setup()`.
2. `SdLogSink::service()` in `loop()`.
3. `SdLogSink::flushNow()` in `enterDeepSleep()` before sleep teardown.
4. `SdLogSink::flushNow()` before each intentional `ESP.restart()`:
   `silentRestart()` (`src/main.cpp`), `OtaUpdateActivity` success, and
   `SdFirmwareUpdateActivity` success. The two activity sites include a
   small `SdLogSink.h` guarded by `CROSSINK_SD_LOG`.

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
  change reset); each release guard refuses with its message; `gh`/`pio`/`git`
  faked via a runner seam.

### Builds

`pio run -e x4-pro-personal`, `x4-pro`, `default`, `simulator` all succeed.
Stock `x4-pro` ELF contains no `SdLogSink` symbols
(`nm .pio/build/x4-pro/firmware.elf | grep -c SdLogSink` = 0).

### Hardware (X4 Pro)

1. First install over USB with `bin/personal flash` (existing firmware points
   OTA at uxjulia). Settings › System shows `1.6.0.1-x4-pro` and the SHA.
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
- GitHub unauthenticated API limit (60/h per IP) is ample for manual checks.
- A mistakenly published prerelease or draft would be invisible to OTA; the
  CLI never creates either.
