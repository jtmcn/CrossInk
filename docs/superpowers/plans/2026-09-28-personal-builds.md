# Personal Builds, OTA Installs, and SD Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `bin/personal` CLI that builds, publishes (OTA via `jtmcn/CrossInk` releases), flashes, syncs, and reports on the CrossInk + freeink-sdk forks as one project, plus an SD-card log sink in the personal X4 Pro build.

**Architecture:** Firmware side: a function-pointer sink hook in `lib/Logging`, a header-only host-tested `LogBuffer` ring, and a device-only `SdLogSink` that the main loop flushes to `/.crosspoint/logs/log.txt`; a new `x4-pro-personal` PlatformIO env turns it on and points OTA at the fork. Tooling side: a stdlib-only Python package `scripts/personal/` behind `bin/personal`, with a `Runner` subprocess seam so every command is tested against fakes or throwaway local git repos.

**Tech Stack:** C++20 (ESP-IDF / Arduino-ESP32 via PlatformIO), GoogleTest via CMake/CTest, Python 3.12 stdlib (`unittest`, `argparse`, `subprocess`), `git`, `gh`, `pio`.

**Spec:** `docs/superpowers/specs/2026-09-28-personal-builds-design.md`

## Global Constraints

- Device scope: X4 Pro only. Stock envs (`default`, `sticky`, `x4-pro`, `x4-classic`, simulators) must build and behave exactly as before.
- Release tags: `v<crossink.version>.<N>`; firmware version string `<base>.<N>-x4-pro`; non-release builds of the personal env are `<base>.0-x4-pro`.
- Releases are created with `gh release create … --latest`; never `--prerelease`, never `--draft`.
- OTA URL for the personal env: `https://api.github.com/repos/jtmcn/CrossInk/releases/latest`.
- Log path `/.crosspoint/logs/log.txt`, rotated to `/.crosspoint/logs/log.1.txt` at 512 KB; RAM buffer 16 KB in PSRAM.
- Flush triggers: pending `ERR` line, buffer ≥ 50 % full, oldest unflushed line ≥ 10 s old; never while `activityManager.requiresExclusiveStorageLoop()`.
- `logPrintf` path never touches storage; only the main loop (and the sleep/restart paths) writes the log file.
- Remotes: CrossInk `upstream` = uxjulia/CrossInk, `origin` = jtmcn/CrossInk; SDK `origin` = Free-Ink/freeink-sdk, `fork` = jtmcn/freeink-sdk. Integration branches: `personal` (CrossInk), `crossink` (SDK). Topics: `joel/*`.
- `sync` pushes nothing until all builds pass (except the fast-forward-only fork `main` mirror pushes) and never force-pushes.
- Python tooling is stdlib only (no pytest installed); tests use `unittest`.
- Commit messages: `<type>: <summary>`, no co-author trailers. Code comments: 1–2 lines, only the non-obvious why.
- Never stage `.pio/`, `compile_commands.json`, `platformio.local.ini`, generated headers, or the `freeink-sdk` gitlink unless the task says so.

## Review Focus

1. **Resuming `sync` after a hand-resolved conflict** — the SDK checkout has moved, so CrossInk shows ` M freeink-sdk`; a rerun must continue, not refuse as dirty. Test: `test_sync_resumes_after_resolved_sdk_conflict` (Task 9).
2. **A release tag that exists on the fork but not locally** — `N` must count remote tags, or two builds share a version and OTA never offers the second. Test: `test_release_counts_tags_only_on_fork` (Task 6).
3. **A log line longer than the 256-byte format buffer** — `logPrintf` truncates without a newline; the file must still be line-oriented. Test: `AppendsMissingNewline` (Task 2).
4. **SD write failure** — the failure's own `LOG_ERR` marks an error pending; without backoff the main loop retries every iteration. Test: `FailedFlushBacksOff` (Task 2).
5. **First run before `personal` exists** — `status` must report the missing branch instead of crashing. Test: `test_status_reports_missing_integration_branch` (Task 8).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `lib/Logging/Logging.{h,cpp}` (modify) | Add `LogSinkFn` / `setLogSink`; call the sink from `logPrintf`. |
| `src/util/LogBuffer.h` (create) | Header-only ring of pending log bytes: append, flush policy, snapshot/commit, backoff, rotation threshold, dropped marker. No platform includes. |
| `src/util/SdLogSink.{h,cpp}` (create) | Device glue: PSRAM buffer, spinlock, boot banner, RTC tail, SD append + rotation. Inline no-ops unless `CROSSINK_SD_LOG`. |
| `src/main.cpp`, `src/activities/settings/{OtaUpdateActivity,SdFirmwareUpdateActivity}.cpp` (modify) | Call sites: begin, wall clock, service, flush before sleep/restart. |
| `test/sd_log_sink/` (create), `test/CMakeLists.txt` (modify) | `LogBufferTest` gtest suite. |
| `platformio.ini` (modify) | `[env:x4-pro-personal]`. |
| `scripts/git_branch.py` (modify), `scripts/test_git_branch_personal.py` (create) | Personal version injection + test. |
| `scripts/personal/proc.py` | `Runner`, `Result`, `PersonalError`. |
| `scripts/personal/project.py` | `Project`, `RepoSpec`, constants for both repos. |
| `scripts/personal/versioning.py` | Base version, build number, tags. |
| `scripts/personal/release.py` | Guards, notes, publish. |
| `scripts/personal/device.py` | Port selection, flash, monitor, log pull. |
| `scripts/personal/topics.py` | Pairing and lifecycle. |
| `scripts/personal/status.py` | Combined two-repo report. |
| `scripts/personal/sync.py` | Upstream catch-up for both forks. |
| `scripts/personal/setup_cmd.py` | Remote verification and git config. |
| `scripts/personal/cli.py`, `__main__.py`, `__init__.py` | argparse dispatch. |
| `scripts/personal/tests/` | `unittest` suites + `gitfixture.py` + `fakes.py`. |
| `bin/personal` | Shell wrapper. |
| `docs/development/personal-builds.md`, `.claude/CONTEXT.md`, `.gitignore` | Docs and `device-logs/`. |

Python test command used throughout (from repo root):

```bash
python3 -m unittest discover -s scripts/personal/tests -t scripts -v
```

---

### Task 1: Log sink hook in `lib/Logging`

**Files:**
- Modify: `lib/Logging/Logging.h` (after the `logPrintf` declaration, ~line 34)
- Modify: `lib/Logging/Logging.cpp` (`logPrintf`, ~lines 50-89)

**Interfaces:**
- Produces: `using LogSinkFn = void (*)(const char* line, size_t len);` and `void setLogSink(LogSinkFn sink);` — the sink receives each fully formatted line (`"[ms] [LVL] [ORIGIN] message\n"`, possibly truncated at 255 bytes without `\n`).

- [ ] **Step 1: Add the declaration** in `lib/Logging/Logging.h` directly below `void logPrintf(...)`:

```cpp
// Receives each formatted line after serial output. Runs on the logging task, so it
// must not block, allocate, or touch storage.
using LogSinkFn = void (*)(const char* line, size_t len);
void setLogSink(LogSinkFn sink);
```

- [ ] **Step 2: Implement it** in `lib/Logging/Logging.cpp`. Above `logPrintf`:

```cpp
static LogSinkFn logSink = nullptr;

void setLogSink(LogSinkFn sink) { logSink = sink; }
```

and at the end of `logPrintf`, after `addToLogRingBuffer(buf);`:

```cpp
  if (logSink) {
    logSink(buf, strnlen(buf, MAX_ENTRY_LEN));
  }
```

- [ ] **Step 3: Build the envs that compile `lib/Logging`**

Run: `pio run -e simulator && pio run -e x4-pro`
Expected: both `SUCCESS`. No sink is registered anywhere yet, so behavior is unchanged.

- [ ] **Step 4: Commit**

```bash
git add lib/Logging/Logging.h lib/Logging/Logging.cpp
git commit -m "feat: add an optional log sink hook to logPrintf"
```

---

### Task 2: `LogBuffer` ring with host tests

**Files:**
- Create: `src/util/LogBuffer.h`
- Create: `test/sd_log_sink/CMakeLists.txt`, `test/sd_log_sink/LogBufferTest.cpp`
- Modify: `test/CMakeLists.txt` (append `add_subdirectory(sd_log_sink)` after the last `add_subdirectory` line)

**Interfaces:**
- Produces (all used by Task 4):
  - `class LogBuffer` with `LogBuffer()`, `void attach(char* storage, size_t capacity)` (capacity must be a power of two), `bool attached() const`, `bool append(const char* line, size_t len, uint32_t nowMs)`, `bool shouldFlush(uint32_t nowMs, bool storageExclusive) const`, `Pending peek() const`, `void commit(const Pending& pending, uint32_t nowMs)`, `void noteFlushFailed(uint32_t nowMs)`, `void noteFlushSucceeded()`, `size_t used() const`, `uint32_t dropped() const`, `bool errorPending() const`, `static bool isErrorLine(const char*, size_t)`, `static constexpr uint32_t kMaxAgeMs = 10000`.
  - `struct LogBuffer::Pending { const char* first; size_t firstLen; const char* second; size_t secondLen; uint32_t dropped; uint32_t endOffset; size_t size() const; }`
  - `inline bool logFileNeedsRotation(size_t fileBytes)` with `constexpr size_t kLogRotateBytes = 512 * 1024`.
  - `inline int formatDroppedMarker(char* buf, size_t len, uint32_t dropped)` writing `"[dropped N lines]\n"`.

- [ ] **Step 1: Register the suite.** Create `test/sd_log_sink/CMakeLists.txt`:

```cmake
add_executable(LogBufferTest LogBufferTest.cpp)
target_link_libraries(LogBufferTest PRIVATE crosspoint_test_common GTest::gtest_main)
gtest_discover_tests(LogBufferTest PROPERTIES ENVIRONMENT "UBSAN_OPTIONS=halt_on_error=1")
```

Append to `test/CMakeLists.txt` after the final `add_subdirectory(...)`:

```cmake
add_subdirectory(sd_log_sink)
```

- [ ] **Step 2: Write the failing tests** in `test/sd_log_sink/LogBufferTest.cpp`:

```cpp
#include <gtest/gtest.h>

#include <string>

#include "src/util/LogBuffer.h"

namespace {

constexpr size_t kCap = 64;

std::string drain(const LogBuffer::Pending& p) {
  std::string out(p.first, p.firstLen);
  if (p.secondLen) out.append(p.second, p.secondLen);
  return out;
}

class LogBufferTest : public ::testing::Test {
 protected:
  void SetUp() override { buffer.attach(storage, kCap); }
  char storage[kCap] = {};
  LogBuffer buffer;
};

TEST_F(LogBufferTest, UnattachedBufferRejectsLines) {
  LogBuffer idle;
  EXPECT_FALSE(idle.attached());
  EXPECT_FALSE(idle.append("x\n", 2, 0));
}

TEST_F(LogBufferTest, AppendsAndPeeksContiguousBytes) {
  ASSERT_TRUE(buffer.append("[1] [INF] [A] hi\n", 17, 0));
  EXPECT_EQ(drain(buffer.peek()), "[1] [INF] [A] hi\n");
  EXPECT_EQ(buffer.used(), 17u);
}

TEST_F(LogBufferTest, AppendsMissingNewline) {
  ASSERT_TRUE(buffer.append("[1] [INF] [A] truncated", 23, 0));
  EXPECT_EQ(drain(buffer.peek()), "[1] [INF] [A] truncated\n");
}

TEST_F(LogBufferTest, WrapsIntoTwoSegments) {
  const std::string a(40, 'a');
  ASSERT_TRUE(buffer.append((a + "\n").c_str(), 41, 0));
  buffer.commit(buffer.peek(), 0);
  const std::string b(30, 'b');
  ASSERT_TRUE(buffer.append((b + "\n").c_str(), 31, 0));
  const auto p = buffer.peek();
  EXPECT_GT(p.secondLen, 0u);
  EXPECT_EQ(drain(p), b + "\n");
}

TEST_F(LogBufferTest, DropsNewestWhenFullAndCounts) {
  const std::string line(40, 'x');
  ASSERT_TRUE(buffer.append((line + "\n").c_str(), 41, 0));
  EXPECT_FALSE(buffer.append((line + "\n").c_str(), 41, 0));
  EXPECT_EQ(buffer.dropped(), 1u);
  const auto p = buffer.peek();
  EXPECT_EQ(p.dropped, 1u);
  EXPECT_EQ(drain(p), line + "\n");
  buffer.commit(p, 0);
  EXPECT_EQ(buffer.dropped(), 0u);
}

TEST_F(LogBufferTest, EmptyBufferNeverFlushes) { EXPECT_FALSE(buffer.shouldFlush(100000, false)); }

TEST_F(LogBufferTest, ErrorLineFlushesImmediately) {
  ASSERT_TRUE(buffer.append("[5] [ERR] [SD] bad\n", 19, 5));
  EXPECT_TRUE(buffer.errorPending());
  EXPECT_TRUE(buffer.shouldFlush(5, false));
}

TEST_F(LogBufferTest, HalfFullFlushes) {
  const std::string line(31, 'h');
  ASSERT_TRUE(buffer.append((line + "\n").c_str(), 32, 0));
  EXPECT_TRUE(buffer.shouldFlush(1, false));
}

TEST_F(LogBufferTest, AgedLineFlushes) {
  ASSERT_TRUE(buffer.append("[0] [INF] [A] x\n", 16, 1000));
  EXPECT_FALSE(buffer.shouldFlush(1000 + LogBuffer::kMaxAgeMs - 1, false));
  EXPECT_TRUE(buffer.shouldFlush(1000 + LogBuffer::kMaxAgeMs, false));
}

TEST_F(LogBufferTest, ExclusiveStorageSuppressesFlush) {
  ASSERT_TRUE(buffer.append("[5] [ERR] [SD] bad\n", 19, 5));
  EXPECT_FALSE(buffer.shouldFlush(5, true));
}

TEST_F(LogBufferTest, CommitKeepsLinesAppendedAfterPeek) {
  ASSERT_TRUE(buffer.append("one\n", 4, 0));
  const auto p = buffer.peek();
  ASSERT_TRUE(buffer.append("two\n", 4, 1));
  buffer.commit(p, 2);
  EXPECT_EQ(drain(buffer.peek()), "two\n");
}

TEST_F(LogBufferTest, ErrorAppendedAfterPeekStaysPending) {
  ASSERT_TRUE(buffer.append("[0] [INF] [A] one\n", 18, 0));
  const auto p = buffer.peek();
  ASSERT_TRUE(buffer.append("[1] [ERR] [A] two\n", 18, 1));
  buffer.commit(p, 2);
  EXPECT_TRUE(buffer.errorPending());
}

TEST_F(LogBufferTest, FailedFlushBacksOff) {
  ASSERT_TRUE(buffer.append("[5] [ERR] [SD] bad\n", 19, 5));
  buffer.noteFlushFailed(10);
  EXPECT_FALSE(buffer.shouldFlush(10 + LogBuffer::kMaxAgeMs - 1, false));
  EXPECT_TRUE(buffer.shouldFlush(10 + LogBuffer::kMaxAgeMs, false));
  buffer.noteFlushSucceeded();
  EXPECT_TRUE(buffer.shouldFlush(11, false));
}

TEST(LogBufferStatic, DetectsErrorLines) {
  EXPECT_TRUE(LogBuffer::isErrorLine("[12] [ERR] [X] m\n", 17));
  EXPECT_FALSE(LogBuffer::isErrorLine("[12] [INF] [X] ERR\n", 19));
  EXPECT_FALSE(LogBuffer::isErrorLine("no brackets", 11));
  EXPECT_FALSE(LogBuffer::isErrorLine("[12]", 4));
}

TEST(LogBufferStatic, RotationThreshold) {
  EXPECT_FALSE(logFileNeedsRotation(kLogRotateBytes - 1));
  EXPECT_TRUE(logFileNeedsRotation(kLogRotateBytes));
}

TEST(LogBufferStatic, DroppedMarkerText) {
  char buf[40];
  const int n = formatDroppedMarker(buf, sizeof(buf), 7);
  EXPECT_EQ(std::string(buf, n), "[dropped 7 lines]\n");
}

}  // namespace
```

- [ ] **Step 3: Run to verify it fails**

Run: `cmake -S test -B build/test -DCMAKE_BUILD_TYPE=Release && cmake --build build/test --target LogBufferTest`
Expected: compile error, `src/util/LogBuffer.h: No such file or directory`.

- [ ] **Step 4: Implement** `src/util/LogBuffer.h`:

```cpp
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>

constexpr size_t kLogRotateBytes = 512 * 1024;

inline bool logFileNeedsRotation(const size_t fileBytes) { return fileBytes >= kLogRotateBytes; }

inline int formatDroppedMarker(char* buf, const size_t len, const uint32_t dropped) {
  return snprintf(buf, len, "[dropped %lu lines]\n", static_cast<unsigned long>(dropped));
}

// Pending log bytes awaiting an SD flush. Not thread-safe; SdLogSink serializes access.
// Drops new lines when full so bytes already peeked stay stable while they are written.
class LogBuffer {
 public:
  static constexpr uint32_t kMaxAgeMs = 10000;

  struct Pending {
    const char* first = nullptr;
    size_t firstLen = 0;
    const char* second = nullptr;
    size_t secondLen = 0;
    uint32_t dropped = 0;
    uint32_t endOffset = 0;
    size_t size() const { return firstLen + secondLen; }
  };

  void attach(char* storage, const size_t capacity) {
    data_ = storage;
    capacity_ = capacity;
    head_ = tail_ = lastErrorEnd_ = dropped_ = 0;
  }
  bool attached() const { return data_ != nullptr; }

  // Matches logPrintf's "[<ms>] [ERR] ..." prefix.
  static bool isErrorLine(const char* line, const size_t len) {
    const auto* close = static_cast<const char*>(memchr(line, ']', len));
    if (close == nullptr) return false;
    const size_t offset = static_cast<size_t>(close - line) + 2;
    return offset + 5 <= len && memcmp(line + offset, "[ERR]", 5) == 0;
  }

  bool append(const char* line, const size_t len, const uint32_t nowMs) {
    if (!attached()) return false;
    if (len == 0) return true;
    const bool needsNewline = line[len - 1] != '\n';
    if (len + (needsNewline ? 1 : 0) > capacity_ - used()) {
      ++dropped_;
      return false;
    }
    if (used() == 0) oldestMs_ = nowMs;
    copyIn(line, len);
    if (needsNewline) copyIn("\n", 1);
    if (isErrorLine(line, len)) lastErrorEnd_ = head_;
    return true;
  }

  bool shouldFlush(const uint32_t nowMs, const bool storageExclusive) const {
    if (storageExclusive || !attached()) return false;
    if (used() == 0 && dropped_ == 0) return false;
    if (failed_ && nowMs - failedAtMs_ < kMaxAgeMs) return false;
    if (errorPending()) return true;
    if (used() * 2 >= capacity_) return true;
    return nowMs - oldestMs_ >= kMaxAgeMs;
  }

  Pending peek() const {
    Pending p;
    p.endOffset = head_;
    p.dropped = dropped_;
    const size_t n = used();
    if (n == 0) return p;
    const size_t start = tail_ & (capacity_ - 1);
    const size_t firstLen = n < capacity_ - start ? n : capacity_ - start;
    p.first = data_ + start;
    p.firstLen = firstLen;
    if (n > firstLen) {
      p.second = data_;
      p.secondLen = n - firstLen;
    }
    return p;
  }

  void commit(const Pending& pending, const uint32_t nowMs) {
    tail_ = pending.endOffset;
    dropped_ -= pending.dropped;
    // Remaining bytes arrived during the write, so "now" is their age origin.
    if (used() > 0) oldestMs_ = nowMs;
  }

  void noteFlushFailed(const uint32_t nowMs) {
    failed_ = true;
    failedAtMs_ = nowMs;
  }
  void noteFlushSucceeded() { failed_ = false; }

  size_t used() const { return static_cast<size_t>(head_ - tail_); }
  uint32_t dropped() const { return dropped_; }
  bool errorPending() const { return static_cast<int32_t>(lastErrorEnd_ - tail_) > 0; }

 private:
  void copyIn(const char* src, const size_t len) {
    const size_t start = head_ & (capacity_ - 1);
    const size_t firstLen = len < capacity_ - start ? len : capacity_ - start;
    memcpy(data_ + start, src, firstLen);
    memcpy(data_, src + firstLen, len - firstLen);
    head_ += static_cast<uint32_t>(len);
  }

  char* data_ = nullptr;
  size_t capacity_ = 0;
  uint32_t head_ = 0;
  uint32_t tail_ = 0;
  uint32_t lastErrorEnd_ = 0;
  uint32_t dropped_ = 0;
  uint32_t oldestMs_ = 0;
  uint32_t failedAtMs_ = 0;
  bool failed_ = false;
};
```

- [ ] **Step 5: Run the suite**

Run: `cmake --build build/test --target LogBufferTest && ctest --test-dir build/test -R 'LogBuffer' --output-on-failure`
Expected: all 16 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/util/LogBuffer.h test/sd_log_sink test/CMakeLists.txt
git commit -m "feat: add a host-tested ring buffer for SD log flushing"
```

---

### Task 3: `x4-pro-personal` env and version injection

**Files:**
- Modify: `platformio.ini` (append after `[env:x4-pro-debug]`, before the X4 Classic comment block)
- Modify: `scripts/git_branch.py` (`inject_version`, plus new `get_personal_version`)
- Create: `scripts/test_git_branch_personal.py`

**Interfaces:**
- Produces: env name `x4-pro-personal`; env var `CROSSINK_PERSONAL_VERSION` (e.g. `1.6.0.7`) consumed at build time; artifact `.pio/build/x4-pro-personal/firmware-x4-pro.bin`; compile definitions `CROSSINK_SD_LOG`, `CROSSINK_OTA_RELEASE_URL`, `LOG_LEVEL=2`.

- [ ] **Step 1: Write the failing test** `scripts/test_git_branch_personal.py`:

```python
#!/usr/bin/env python3
"""Personal-build version injection in scripts/git_branch.py."""

import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_git_branch():
    spec = importlib.util.spec_from_file_location('git_branch_under_test', ROOT / 'scripts' / 'git_branch.py')
    module = importlib.util.module_from_spec(spec)
    with mock.patch('builtins.print'):
        spec.loader.exec_module(module)
    return module


class PersonalVersionTest(unittest.TestCase):
    def test_uses_release_number_from_env(self):
        gb = load_git_branch()
        with mock.patch.dict(os.environ, {'CROSSINK_PERSONAL_VERSION': '1.6.0.7'}):
            self.assertEqual(gb.get_personal_version(str(ROOT)), '1.6.0.7-x4-pro')

    def test_local_builds_are_build_zero(self):
        gb = load_git_branch()
        env = {k: v for k, v in os.environ.items() if k != 'CROSSINK_PERSONAL_VERSION'}
        with mock.patch.dict(os.environ, env, clear=True):
            base = gb.get_crossink_version(str(ROOT))
            self.assertEqual(gb.get_personal_version(str(ROOT)), f'{base}.0-x4-pro')


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 scripts/test_git_branch_personal.py -v`
Expected: FAIL/ERROR with `AttributeError: module 'git_branch_under_test' has no attribute 'get_personal_version'`.

- [ ] **Step 3: Implement** in `scripts/git_branch.py`. Add below `get_hardware_version`:

```python
def get_personal_version(project_dir):
    # Local builds are build 0 so they never outrank a published personal release.
    version = os.environ.get('CROSSINK_PERSONAL_VERSION') or f'{get_crossink_version(project_dir)}.0'
    return f'{sanitize_version_component(version)}-x4-pro'
```

and in `inject_version`, add a branch before `elif pioenv == 'debug':`:

```python
    elif pioenv == 'x4-pro-personal':
        version_string = get_personal_version(project_dir)
        env.Append(CPPDEFINES=[('CROSSINK_VERSION', f'\\"{version_string}\\"')])
        print(f'CrossInk personal build version: {version_string}')
```

- [ ] **Step 4: Run the test**

Run: `python3 scripts/test_git_branch_personal.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Add the env** to `platformio.ini` after the `[env:x4-pro-debug]` section:

```ini
; Personal daily build: OTA from the jtmcn fork, SD log sink, debug-level logs.
[env:x4-pro-personal]
extends = env:x4-pro
build_flags =
  ${env:x4-pro.build_flags}
  -DCROSSINK_OTA_RELEASE_URL=\"https://api.github.com/repos/jtmcn/CrossInk/releases/latest\"
  -DCROSSINK_SD_LOG
  -DLOG_LEVEL=2
build_unflags =
  ${base.build_unflags}
  -DLOG_LEVEL=1
```

- [ ] **Step 6: Build and check flags and version**

Run: `CROSSINK_PERSONAL_VERSION=1.6.0.99 pio run -e x4-pro-personal -v > .pio/x4-pro-personal-verbose.log 2>&1; grep -E "CrossInk personal build version|SUCCESS|FAILED" .pio/x4-pro-personal-verbose.log; grep -o 'DLOG_LEVEL=[0-9]' .pio/x4-pro-personal-verbose.log | sort | uniq -c; ls .pio/build/x4-pro-personal/firmware-x4-pro.bin`
Expected: `CrossInk personal build version: 1.6.0.99-x4-pro`, `SUCCESS`, only `DLOG_LEVEL=2` counted (no `=1`), artifact exists.
If `DLOG_LEVEL=1` still appears, `build_unflags` did not match; replace the `build_flags` block with a copy of `[env:x4-pro]`'s flags, with `-DLOG_LEVEL=2` instead of `=1` and without the unflags section, and rebuild.

- [ ] **Step 7: Confirm stock `x4-pro` is unaffected**

Run: `pio run -e x4-pro 2>&1 | grep -E "CrossInk build version|SUCCESS"`
Expected: `CrossInk build version: 1.6.0-x4-pro` and `SUCCESS`.

- [ ] **Step 8: Commit**

```bash
git add platformio.ini scripts/git_branch.py scripts/test_git_branch_personal.py
git commit -m "feat: add the x4-pro-personal build env with fork OTA and build-numbered versions"
```

---

### Task 4: `SdLogSink` and firmware call sites

**Files:**
- Create: `src/util/SdLogSink.h`, `src/util/SdLogSink.cpp`
- Modify: `src/main.cpp` — include block (~line 114), `restartWithSilentToken()` (~line 363), `enterDeepSleep()` before `Storage.shutdown()` (~line 1101), `setup()` before `HalSystem::begin()` (~line 1201) and after `APP_STATE.loadFromFile()` (~line 1315), `loop()` after the exclusive-storage block (~line 1597)
- Modify: `src/activities/settings/OtaUpdateActivity.cpp` (~line 305), `src/activities/settings/SdFirmwareUpdateActivity.cpp` (~line 189)

**Interfaces:**
- Consumes: `setLogSink`, `getLastLogs` (Task 1 / existing `Logging.h`); `LogBuffer`, `logFileNeedsRotation`, `formatDroppedMarker` (Task 2); `makePsramByteBufferNoThrow` / `HeapByteBuffer` (`lib/Memory/Memory.h`); `getCurrentLocalReadingStatsDateTime` (`src/activities/reader/ReadingStatsUtils.h`).
- Produces: `namespace SdLogSink { void begin(int resetReason, const char* resetReasonName); void logWallClock(); void service(); void flushNow(); }` — inline no-ops unless `CROSSINK_SD_LOG`.

- [ ] **Step 1: Header** `src/util/SdLogSink.h`:

```cpp
#pragma once

// Copies log lines to PSRAM and appends them to /.crosspoint/logs/log.txt from the main
// loop. Personal builds only (-DCROSSINK_SD_LOG); other builds get inline no-ops.
namespace SdLogSink {

#ifdef CROSSINK_SD_LOG
// Call before HalSystem::begin(): it clears the RTC log ring on non-panic boots.
void begin(int resetReason, const char* resetReasonName);
void logWallClock();
// Only call where storage is not exclusively owned (USB Drive, serial transfer).
void service();
void flushNow();
#else
inline void begin(int, const char*) {}
inline void logWallClock() {}
inline void service() {}
inline void flushNow() {}
#endif

}  // namespace SdLogSink
```

- [ ] **Step 2: Implementation** `src/util/SdLogSink.cpp`:

```cpp
#include "SdLogSink.h"

#ifdef CROSSINK_SD_LOG

#include <Arduino.h>
#include <HalStorage.h>
#include <Logging.h>
#include <Memory.h>
#include <esp_system.h>
#include <freertos/FreeRTOS.h>

#include <algorithm>
#include <cstdio>
#include <string>

#include "AppVersion.h"
#include "LogBuffer.h"
#include "activities/reader/ReadingStatsUtils.h"

namespace SdLogSink {
namespace {

constexpr size_t BUFFER_BYTES = 16 * 1024;
static_assert((BUFFER_BYTES & (BUFFER_BYTES - 1)) == 0, "LogBuffer capacity must be a power of two");
constexpr char LOG_DIR[] = "/.crosspoint/logs";
constexpr char LOG_PATH[] = "/.crosspoint/logs/log.txt";
constexpr char OLD_LOG_PATH[] = "/.crosspoint/logs/log.1.txt";

portMUX_TYPE bufferLock = portMUX_INITIALIZER_UNLOCKED;
HeapByteBuffer bufferStorage;
LogBuffer buffer;
bool writeFailureReported = false;

void appendLine(const char* line, const size_t len) {
  const uint32_t now = millis();
  portENTER_CRITICAL(&bufferLock);
  buffer.append(line, len, now);
  portEXIT_CRITICAL(&bufferLock);
}

bool keepsResetTail(const int reason) {
  switch (reason) {
    case ESP_RST_PANIC:
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT:
    case ESP_RST_BROWNOUT:
    case ESP_RST_CPU_LOCKUP:
      return true;
    default:
      return false;
  }
}

size_t currentLogBytes() {
  if (!Storage.exists(LOG_PATH)) return 0;
  HalFile probe = Storage.open(LOG_PATH, O_RDONLY);
  if (!probe) return 0;
  const size_t bytes = probe.size();
  probe.close();
  return bytes;
}

bool writeSpan(HalFile& file, const char* data, const size_t len) { return len == 0 || file.write(data, len) == len; }

bool writePending(const LogBuffer::Pending& pending) {
  if (!Storage.ensureDirectoryExists(LOG_DIR)) return false;
  if (logFileNeedsRotation(currentLogBytes())) {
    if (Storage.exists(OLD_LOG_PATH) && !Storage.remove(OLD_LOG_PATH)) return false;
    if (!Storage.rename(LOG_PATH, OLD_LOG_PATH)) return false;
  }
  HalFile file = Storage.open(LOG_PATH, O_WRONLY | O_CREAT | O_APPEND);
  if (!file) return false;
  bool ok = writeSpan(file, pending.first, pending.firstLen) && writeSpan(file, pending.second, pending.secondLen);
  if (ok && pending.dropped > 0) {
    char marker[40];
    const int n = formatDroppedMarker(marker, sizeof(marker), pending.dropped);
    ok = n > 0 && writeSpan(file, marker, static_cast<size_t>(n));
  }
  file.close();
  return ok;
}

void flushOnce() {
  if (!buffer.attached() || !Storage.ready()) return;
  portENTER_CRITICAL(&bufferLock);
  const LogBuffer::Pending pending = buffer.peek();
  portEXIT_CRITICAL(&bufferLock);
  if (pending.size() == 0 && pending.dropped == 0) return;

  // Written outside the lock: producers only append past pending.endOffset.
  const bool ok = writePending(pending);
  const uint32_t now = millis();
  portENTER_CRITICAL(&bufferLock);
  if (ok) {
    buffer.commit(pending, now);
    buffer.noteFlushSucceeded();
  } else {
    buffer.noteFlushFailed(now);
  }
  portEXIT_CRITICAL(&bufferLock);
  if (!ok && !writeFailureReported) {
    writeFailureReported = true;
    LOG_ERR("SDLOG", "Failed to append %s; keeping lines buffered", LOG_PATH);
  }
}

}  // namespace

void begin(const int resetReason, const char* const resetReasonName) {
  const std::string tail = keepsResetTail(resetReason) ? getLastLogs() : std::string();
  // PSRAM keeps 16 KB of diagnostics out of internal RAM; it lives for the whole boot.
  bufferStorage = makePsramByteBufferNoThrow(BUFFER_BYTES);
  if (!bufferStorage) {
    LOG_ERR("SDLOG", "No PSRAM for the %u-byte log buffer; SD logging disabled", static_cast<unsigned>(BUFFER_BYTES));
    return;
  }
  buffer.attach(reinterpret_cast<char*>(bufferStorage.get()), BUFFER_BYTES);

  char banner[192];
  const int n = snprintf(banner, sizeof(banner), "=== boot %s sha=%s dirty=%s reset=%s ===\n", CROSSINK_VERSION,
                         CROSSINK_GIT_SHA, CROSSINK_GIT_DIRTY, resetReasonName);
  if (n > 0) appendLine(banner, std::min(static_cast<size_t>(n), sizeof(banner) - 1));
  if (!tail.empty()) {
    static constexpr char header[] = "--- last lines before reset ---\n";
    static constexpr char footer[] = "--- end of reset tail ---\n";
    appendLine(header, sizeof(header) - 1);
    appendLine(tail.data(), tail.size());
    appendLine(footer, sizeof(footer) - 1);
  }
  setLogSink(appendLine);
}

void logWallClock() {
  ReadingStatsDateTime now;
  if (!getCurrentLocalReadingStatsDateTime(now)) {
    LOG_INF("SDLOG", "clock unset");
    return;
  }
  LOG_INF("SDLOG", "clock %04u-%02u-%02uT%02u:%02u:%02u", static_cast<unsigned>(now.date.year),
          static_cast<unsigned>(now.date.month), static_cast<unsigned>(now.date.day), static_cast<unsigned>(now.hour),
          static_cast<unsigned>(now.minute), static_cast<unsigned>(now.second));
}

void service() {
  if (!buffer.attached()) return;
  const uint32_t now = millis();
  portENTER_CRITICAL(&bufferLock);
  const bool due = buffer.shouldFlush(now, false);
  portEXIT_CRITICAL(&bufferLock);
  if (due) flushOnce();
}

void flushNow() { flushOnce(); }

}  // namespace SdLogSink

#endif  // CROSSINK_SD_LOG
```

`<Memory.h>` is `lib/Memory/Memory.h`, included the same way as `src/main.cpp:19`.

- [ ] **Step 3: Call sites in `src/main.cpp`**

Include (next to `#include "util/BatteryDiagnosticLog.h"`):

```cpp
#include "util/SdLogSink.h"
```

In `setup()`, immediately before `HalSystem::begin();`:

```cpp
  SdLogSink::begin(static_cast<int>(rawResetReason), resetReasonName(rawResetReason));
```

In `setup()`, immediately after `APP_STATE.loadFromFile();`:

```cpp
  SdLogSink::logWallClock();
```

In `loop()`, immediately after the closing `}` of the `if (activityManager.requiresExclusiveStorageLoop()) { ... return; }` block:

```cpp
  // Placed after the exclusive-storage early return so USB Drive never sees a write.
  SdLogSink::service();
```

In `enterDeepSleep()`, immediately before `Storage.shutdown();`:

```cpp
  SdLogSink::flushNow();
```

In `restartWithSilentToken()`, immediately before `ESP.restart();`:

```cpp
  SdLogSink::flushNow();
```

- [ ] **Step 4: Call sites in the firmware-update activities**

`src/activities/settings/OtaUpdateActivity.cpp`: add `#include "util/SdLogSink.h"` to the quoted includes, and change the shutdown branch to:

```cpp
  if (state == SHUTTING_DOWN) {
    SdLogSink::flushNow();
    ESP.restart();
  }
```

`src/activities/settings/SdFirmwareUpdateActivity.cpp`: add `#include "util/SdLogSink.h"` to the quoted includes, and insert `SdLogSink::flushNow();` on the line before the `ESP.restart();` that follows `delay(1500);`.

- [ ] **Step 5: Build every affected env**

Run: `pio run -e x4-pro-personal && pio run -e x4-pro && pio run -e default && pio run -e simulator`
Expected: all `SUCCESS`.

- [ ] **Step 6: Confirm the stock build carries no sink**

Run: `NM=$(find ~/.platformio/packages -name 'xtensa-esp32s3-elf-nm' -type f | head -1); "$NM" -C .pio/build/x4-pro/firmware.elf | grep -c SdLogSink; "$NM" -C .pio/build/x4-pro-personal/firmware.elf | grep -c SdLogSink`
Expected: first count `0`, second count > `0`.

- [ ] **Step 7: Format and rerun host tests**

Run: `./bin/clang-format-fix && git diff --stat && ctest --test-dir build/test -R 'LogBuffer' --output-on-failure`
Expected: formatting touches only files from this task (if any); tests PASS.

- [ ] **Step 8: Commit**

```bash
git add src/util/SdLogSink.h src/util/SdLogSink.cpp src/main.cpp src/activities/settings/OtaUpdateActivity.cpp src/activities/settings/SdFirmwareUpdateActivity.cpp
git commit -m "feat: log to the SD card from the personal X4 Pro build"
```

---

### Task 5: Python package core, CLI skeleton, wrapper

**Files:**
- Create: `scripts/personal/__init__.py` (empty), `scripts/personal/__main__.py`, `scripts/personal/proc.py`, `scripts/personal/project.py`, `scripts/personal/versioning.py`, `scripts/personal/cli.py`
- Create: `scripts/personal/tests/__init__.py` (empty), `scripts/personal/tests/fakes.py`, `scripts/personal/tests/test_versioning.py`
- Create: `bin/personal` (mode 755)
- Modify: `.gitignore` (append `device-logs/`)

**Interfaces:**
- Produces:
  - `proc.PersonalError(Exception)`; `proc.Result(returncode: int, stdout: str = '', stderr: str = '')`; `proc.Runner.run(argv, cwd=None, env=None, check=True, stream=False) -> Result` (`env` is merged over `os.environ`; `stream=True` inherits the terminal).
  - `project.APP = 'app'`, `project.SDK = 'sdk'`, `project.RepoSpec(name, upstream_remote, fork_remote, integration, upstream_slug, fork_slug)`, `APP_SPEC`, `SDK_SPEC`, `TOPIC_PREFIX = 'joel/'`, `PERSONAL_ENV`, `DEBUG_ENV`, `SYNC_BUILD_ENVS`, `ARTIFACT`, `SDK_PATH`.
  - `project.Project(root: Path, runner: Runner)` with `path(repo) -> Path`, `spec(repo) -> RepoSpec`, `git(repo, *args, check=True) -> str` (stripped stdout), `git_ok(repo, *args) -> bool`, `upstream_main(repo) -> str`, `pinned_sdk(rev='HEAD') -> str`.
  - `versioning.base_version(root: Path) -> str`, `next_build_number(tags, base) -> int`, `release_tag(base, n) -> str`, `latest_release_tag(tags) -> str | None`, `version_at_head(tags_at_head, base) -> str | None`.
  - `fakes.FakeRunner(responses: dict[tuple, Result] | None)` recording `calls: list[dict]`; `fakes.ToolFake(Runner)` running real `git`, faking `pio`/`gh` (see Step 3).
  - `cli.main(argv=None) -> int`, `cli.ROOT`.

- [ ] **Step 1: Write the failing test** `scripts/personal/tests/test_versioning.py`:

```python
import tempfile
import unittest
from pathlib import Path

from personal import versioning
from personal.proc import PersonalError


class VersioningTest(unittest.TestCase):
    def test_first_build_of_a_base_is_one(self):
        self.assertEqual(versioning.next_build_number(['v1.5.0.9', 'v1.6.0'], '1.6.0'), 1)

    def test_next_build_increments_highest(self):
        tags = ['v1.6.0.1', 'v1.6.0.10', 'v1.6.0.2']
        self.assertEqual(versioning.next_build_number(tags, '1.6.0'), 11)

    def test_base_change_resets(self):
        self.assertEqual(versioning.next_build_number(['v1.6.0.4'], '1.7.0'), 1)

    def test_release_tag(self):
        self.assertEqual(versioning.release_tag('1.6.0', 3), 'v1.6.0.3')

    def test_latest_release_tag_orders_numerically(self):
        tags = ['v1.6.0.9', 'v1.6.0.10', 'v1.5.9.99', 'v1.6.0', 'junk']
        self.assertEqual(versioning.latest_release_tag(tags), 'v1.6.0.10')
        self.assertIsNone(versioning.latest_release_tag(['v1.6.0']))

    def test_version_at_head(self):
        self.assertEqual(versioning.version_at_head(['v1.6.0.2', 'v1.6.0.3'], '1.6.0'), '1.6.0.3')
        self.assertIsNone(versioning.version_at_head(['v1.5.0.3'], '1.6.0'))

    def test_base_version_reads_ini_and_local_override(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'platformio.ini').write_text('[crossink]\nversion = 1.6.0\n')
            self.assertEqual(versioning.base_version(root), '1.6.0')
            (root / 'platformio.local.ini').write_text('[crossink]\nversion = 1.7.0\n')
            self.assertEqual(versioning.base_version(root), '1.7.0')

    def test_base_version_rejects_non_semver(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'platformio.ini').write_text('[crossink]\nversion = 1.6\n')
            with self.assertRaises(PersonalError):
                versioning.base_version(root)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest discover -s scripts/personal/tests -t scripts -v`
Expected: ERROR `ModuleNotFoundError: No module named 'personal'` (package not created yet; create empty `scripts/personal/__init__.py` and `scripts/personal/tests/__init__.py` first, then it fails with `cannot import name 'versioning'`).

- [ ] **Step 3: Implement the core modules**

`scripts/personal/proc.py`:

```python
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
```

`scripts/personal/project.py`:

```python
"""The CrossInk + freeink-sdk fork pair, addressed as one project."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .proc import Runner

APP = 'app'
SDK = 'sdk'
SDK_PATH = 'freeink-sdk'
TOPIC_PREFIX = 'joel/'
PERSONAL_ENV = 'x4-pro-personal'
DEBUG_ENV = 'x4-pro-debug'
SYNC_BUILD_ENVS = (PERSONAL_ENV, 'default', 'simulator')
ARTIFACT = Path('.pio') / 'build' / PERSONAL_ENV / 'firmware-x4-pro.bin'


@dataclass(frozen=True)
class RepoSpec:
    name: str
    upstream_remote: str
    fork_remote: str
    integration: str
    upstream_slug: str
    fork_slug: str


APP_SPEC = RepoSpec('CrossInk', 'upstream', 'origin', 'personal', 'uxjulia/CrossInk', 'jtmcn/CrossInk')
SDK_SPEC = RepoSpec('freeink-sdk', 'origin', 'fork', 'crossink', 'Free-Ink/freeink-sdk', 'jtmcn/freeink-sdk')


@dataclass
class Project:
    root: Path
    runner: Runner = field(default_factory=Runner)

    def path(self, repo: str) -> Path:
        return self.root if repo == APP else self.root / SDK_PATH

    def spec(self, repo: str) -> RepoSpec:
        return APP_SPEC if repo == APP else SDK_SPEC

    def git(self, repo: str, *args, check: bool = True) -> str:
        return self.runner.run(['git', *args], cwd=self.path(repo), check=check).stdout.strip()

    def git_ok(self, repo: str, *args) -> bool:
        return self.runner.run(['git', *args], cwd=self.path(repo), check=False).returncode == 0

    def upstream_main(self, repo: str) -> str:
        return f'{self.spec(repo).upstream_remote}/main'

    def pinned_sdk(self, rev: str = 'HEAD') -> str:
        # ls-tree prints "160000 commit <sha>\tfreeink-sdk" for the gitlink.
        out = self.git(APP, 'ls-tree', rev, SDK_PATH, check=False)
        return out.split()[2] if out else ''
```

`scripts/personal/versioning.py`:

```python
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
```

`scripts/personal/cli.py`:

```python
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
    flash.add_argument('--debug', action='store_true', help='flash x4-pro-debug instead')
    sub.add_parser('monitor', help='serial monitor, saved under device-logs/')
    sub.add_parser('logs', help='copy SD logs from a mounted USB Drive volume')
    return parser


def dispatch(project: Project, args) -> None:
    raise PersonalError(f'`{args.command}` is not implemented yet')


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        dispatch(Project(ROOT), args)
    except PersonalError as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    return 0
```

`scripts/personal/__main__.py`:

```python
import sys

from .cli import main

sys.exit(main())
```

`scripts/personal/tests/fakes.py`:

```python
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
```

`bin/personal`:

```bash
#!/usr/bin/env bash
# Entry point for personal fork builds; see docs/development/personal-builds.md.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec env PYTHONPATH="$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}" python3 -m personal "$@"
```

Append to `.gitignore`:

```
device-logs/
```

- [ ] **Step 4: Run the tests and the wrapper**

Run: `chmod +x bin/personal && python3 -m unittest discover -s scripts/personal/tests -t scripts -v && bin/personal --help && bin/personal status; echo "exit=$?"`
Expected: 8 versioning tests PASS; help lists the 7 subcommands; `status` prints `error: \`status\` is not implemented yet` and `exit=1`.

- [ ] **Step 5: Commit**

```bash
git add scripts/personal bin/personal .gitignore
git commit -m "feat: scaffold the bin/personal fork-pair CLI with release numbering"
```

---

### Task 6: Git fixture and `release`

**Files:**
- Create: `scripts/personal/tests/gitfixture.py`, `scripts/personal/release.py`, `scripts/personal/tests/test_release.py`
- Modify: `scripts/personal/cli.py` (`dispatch`)

**Interfaces:**
- Consumes: Task 5 `Project`, `versioning`, `ToolFake`.
- Produces:
  - `gitfixture.Fixture` with attributes `root`, `sdk`, `app_upstream`, `app_fork`, `sdk_upstream`, `sdk_fork`, and methods `commit(repo, name, text, message)`, `add_sdk_topic(name, filename, text='topic\n')`, `add_app_topic(name, base='upstream/main', bump_sdk=False, merge=True)`, `advance_sdk_upstream(filename, text)`, `advance_app_upstream(filename, text, pin_sdk=None)`, `remote_sha(bare, ref)`, `cleanup()`; module helper `git(cwd, *args) -> str`.
  - `release.check_guards(p) -> list[str]` (warnings; raises `PersonalError` on refusal), `release.release_notes(p, pin, previous_tag) -> str`, `release.release(p, out=print) -> str` (returns the tag).

- [ ] **Step 1: Write the fixture** `scripts/personal/tests/gitfixture.py`:

```python
"""Throwaway upstream/fork bare repos for both projects plus a local CrossInk clone with the SDK submodule."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

GIT_ENV = {
    'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.com',
    'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.com',
    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
    'GIT_CONFIG_COUNT': '2',
    'GIT_CONFIG_KEY_0': 'protocol.file.allow', 'GIT_CONFIG_VALUE_0': 'always',
    'GIT_CONFIG_KEY_1': 'init.defaultBranch', 'GIT_CONFIG_VALUE_1': 'main',
}


def git(cwd, *args) -> str:
    return subprocess.run(['git', *map(str, args)], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


class Fixture:
    def __init__(self):
        self._saved_env = dict(os.environ)
        os.environ.update(GIT_ENV)
        self._tmp = tempfile.TemporaryDirectory(prefix='personal-fixture-')
        t = Path(self._tmp.name)
        self.tmp = t
        self.sdk_upstream, self.sdk_fork = t / 'sdk-up.git', t / 'sdk-fork.git'
        self.app_upstream, self.app_fork = t / 'app-up.git', t / 'app-fork.git'
        for bare in (self.sdk_upstream, self.sdk_fork, self.app_upstream, self.app_fork):
            git(t, 'init', '-q', '--bare', bare)

        seed = t / 'sdk-seed'
        git(t, 'init', '-q', seed)
        self.commit(seed, 'lib.txt', 'v1\n', 'sdk: initial')
        git(seed, 'push', '-q', self.sdk_upstream, 'main')
        git(seed, 'push', '-q', self.sdk_fork, 'main')

        app_seed = t / 'app-seed'
        git(t, 'init', '-q', app_seed)
        (app_seed / 'platformio.ini').write_text('[crossink]\nversion = 1.6.0\n')
        git(app_seed, 'submodule', 'add', '-q', self.sdk_fork, 'freeink-sdk')
        git(app_seed, 'add', '-A')
        git(app_seed, 'commit', '-q', '-m', 'app: initial')
        git(app_seed, 'push', '-q', self.app_upstream, 'main')
        git(app_seed, 'push', '-q', self.app_fork, 'main')

        self.root = t / 'CrossInk'
        git(t, 'clone', '-q', '--recurse-submodules', self.app_fork, self.root)
        git(self.root, 'remote', 'add', 'upstream', self.app_upstream)
        git(self.root, 'fetch', '-q', 'upstream')
        self.sdk = self.root / 'freeink-sdk'
        git(self.sdk, 'remote', 'rename', 'origin', 'fork')
        git(self.sdk, 'remote', 'add', 'origin', self.sdk_upstream)
        git(self.sdk, 'fetch', '-q', 'origin')
        git(self.sdk, 'checkout', '-q', '-b', 'crossink', 'origin/main')
        git(self.sdk, 'push', '-q', 'fork', 'crossink')
        git(self.root, 'checkout', '-q', '-b', 'personal', 'upstream/main')
        git(self.root, 'push', '-q', 'origin', 'personal')

    @staticmethod
    def commit(repo, name, text, message):
        (Path(repo) / name).write_text(text)
        git(repo, 'add', name)
        git(repo, 'commit', '-q', '-m', message)

    def add_sdk_topic(self, name, filename, text='topic\n'):
        git(self.sdk, 'checkout', '-q', '-b', name, 'origin/main')
        self.commit(self.sdk, filename, text, f'sdk: {name}')
        git(self.sdk, 'push', '-q', 'fork', name)
        git(self.sdk, 'checkout', '-q', 'crossink')
        git(self.sdk, 'merge', '-q', '--no-ff', name, '-m', f"Merge branch '{name}' into crossink")
        git(self.sdk, 'push', '-q', 'fork', 'crossink')

    def add_app_topic(self, name, base='upstream/main', bump_sdk=False, merge=True):
        git(self.root, 'checkout', '-q', '-b', name, base)
        self.commit(self.root, name.replace('/', '-') + '.txt', 'x\n', f'feat: {name}')
        if bump_sdk:
            git(self.root, 'add', 'freeink-sdk')
            git(self.root, 'commit', '-q', '-m', f'chore: pin sdk for {name}')
        git(self.root, 'push', '-q', 'origin', name)
        git(self.root, 'checkout', '-q', 'personal')
        if merge:
            git(self.root, 'merge', '-q', '--no-ff', name, '-m', f"Merge branch '{name}' into personal")
            git(self.root, 'push', '-q', 'origin', 'personal')

    def _work_clone(self, bare, name):
        work = self.tmp / name
        if not work.exists():
            git(self.tmp, 'clone', '-q', bare, work)
        git(work, 'pull', '-q', 'origin', 'main')
        return work

    def advance_sdk_upstream(self, filename, text):
        work = self._work_clone(self.sdk_upstream, 'sdk-up-work')
        self.commit(work, filename, text, f'upstream sdk: {filename}')
        git(work, 'push', '-q', 'origin', 'main')
        return git(work, 'rev-parse', 'HEAD')

    def advance_app_upstream(self, filename, text, pin_sdk=None):
        work = self._work_clone(self.app_upstream, 'app-up-work')
        self.commit(work, filename, text, f'upstream app: {filename}')
        if pin_sdk:
            git(work, 'update-index', '--cacheinfo', f'160000,{pin_sdk},freeink-sdk')
            git(work, 'commit', '-q', '-m', 'upstream app: bump sdk')
        git(work, 'push', '-q', 'origin', 'main')

    @staticmethod
    def remote_sha(bare, ref):
        return git(bare, 'rev-parse', ref)

    def cleanup(self):
        self._tmp.cleanup()
        os.environ.clear()
        os.environ.update(self._saved_env)
```

- [ ] **Step 2: Write the failing tests** `scripts/personal/tests/test_release.py`:

```python
import unittest

from personal import release
from personal.proc import PersonalError, Result
from personal.project import ARTIFACT, Project
from personal.tests.fakes import ToolFake
from personal.tests.gitfixture import Fixture, git


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)
        self.tools = ToolFake(artifact=self.fx.root / ARTIFACT)
        self.p = Project(self.fx.root, self.tools)

    def assertRefuses(self, fragment):
        with self.assertRaises(PersonalError) as ctx:
            release.check_guards(self.p)
        self.assertIn(fragment, str(ctx.exception))

    def test_refuses_off_personal(self):
        git(self.fx.root, 'checkout', '-q', '-b', 'joel/elsewhere')
        self.assertRefuses('release runs on `personal`')

    def test_refuses_dirty_tree(self):
        (self.fx.root / 'platformio.ini').write_text('[crossink]\nversion = 1.6.0\n# edit\n')
        self.assertRefuses('uncommitted changes')

    def test_refuses_unpushed_personal(self):
        self.fx.commit(self.fx.root, 'local.txt', 'x\n', 'local only')
        self.assertRefuses('differs from `origin/personal`')

    def test_refuses_pin_missing_from_fork_crossink(self):
        self.fx.commit(self.fx.sdk, 'unpushed.txt', 'x\n', 'sdk: unpushed')
        git(self.fx.root, 'add', 'freeink-sdk')
        git(self.fx.root, 'commit', '-q', '-m', 'pin unpushed sdk')
        git(self.fx.root, 'push', '-q', 'origin', 'personal')
        self.assertRefuses('is not on `fork/crossink`')

    def test_refuses_without_gh_auth(self):
        self.tools.gh_responses[('gh', 'auth', 'status')] = Result(1, '', 'not logged in')
        self.assertRefuses('gh auth status')

    def test_warns_when_behind_upstream(self):
        self.fx.advance_app_upstream('new.txt', 'x\n')
        warnings = release.check_guards(self.p)
        self.assertTrue(any('CrossInk' in w and 'behind upstream' in w for w in warnings))

    def test_release_builds_tags_and_publishes(self):
        tag = release.release(self.p, out=lambda *_: None)
        self.assertEqual(tag, 'v1.6.0.1')
        pio_calls = [c for c in self.tools.calls if c['argv'][0] == 'pio']
        self.assertEqual([c['argv'] for c in pio_calls], [['pio', 'run', '-e', 'x4-pro-personal']])
        self.assertEqual(pio_calls[0]['env'], {'CROSSINK_PERSONAL_VERSION': '1.6.0.1'})
        self.assertIn('v1.6.0.1', git(self.fx.app_fork, 'tag', '--list'))
        create = [c for c in self.tools.tool_calls('gh') if c[1:3] == ['release', 'create']][0]
        self.assertIn('--latest', create)
        self.assertNotIn('--prerelease', create)
        self.assertNotIn('--draft', create)
        self.assertIn('jtmcn/CrossInk', create)
        self.assertEqual(release.release(self.p, out=lambda *_: None), 'v1.6.0.2')

    def test_release_counts_tags_only_on_fork(self):
        other = self.fx.tmp / 'other-clone'
        git(self.fx.tmp, 'clone', '-q', self.fx.app_fork, other)
        git(other, 'tag', 'v1.6.0.3', 'origin/personal')
        git(other, 'push', '-q', 'origin', 'v1.6.0.3')
        self.assertEqual(release.release(self.p, out=lambda *_: None), 'v1.6.0.4')

    def test_upload_failure_keeps_tag_and_prints_retry(self):
        self.tools.gh_responses[('gh', 'release', 'create')] = Result(1, '', 'upload broke')
        with self.assertRaises(PersonalError) as ctx:
            release.release(self.p, out=lambda *_: None)
        self.assertIn('retry with', str(ctx.exception))
        self.assertIn('gh release create v1.6.0.1', str(ctx.exception))
        self.assertIn('v1.6.0.1', git(self.fx.app_fork, 'tag', '--list'))

    def test_notes_include_merges_and_sdk_delta(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        notes = release.release_notes(self.p, self.p.pinned_sdk(), None)
        self.assertIn("Merge branch 'joel/app-a' into personal", notes)
        self.assertIn('a.txt', notes)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 3: Run to verify it fails**

Run: `python3 -m unittest discover -s scripts/personal/tests -t scripts -p 'test_release.py' -v`
Expected: ERROR `cannot import name 'release' from 'personal'`.

- [ ] **Step 4: Implement** `scripts/personal/release.py`:

```python
"""Build and publish a personal OTA release on the CrossInk fork."""

from __future__ import annotations

import shlex
import tempfile

from . import versioning
from .proc import PersonalError
from .project import APP, ARTIFACT, PERSONAL_ENV, SDK, SDK_PATH, Project


def _require(condition, message):
    if not condition:
        raise PersonalError(message)


def check_guards(p: Project) -> list[str]:
    app, sdk = p.spec(APP), p.spec(SDK)
    branch = p.git(APP, 'rev-parse', '--abbrev-ref', 'HEAD')
    _require(branch == app.integration, f'release runs on `{app.integration}`, not `{branch}`')
    dirty = p.git(APP, 'status', '--porcelain', '--untracked-files=no')
    _require(not dirty, f'CrossInk has uncommitted changes (a moved {SDK_PATH} checkout counts):\n{dirty}')
    sdk_dirty = p.git(SDK, 'status', '--porcelain', '--untracked-files=no')
    _require(not sdk_dirty, f'{SDK_PATH} has uncommitted changes:\n{sdk_dirty}')

    p.git(APP, 'fetch', '--quiet', app.fork_remote)
    fork_ref = f'{app.fork_remote}/{app.integration}'
    _require(p.git_ok(APP, 'rev-parse', '--verify', '--quiet', fork_ref)
             and p.git(APP, 'rev-parse', 'HEAD') == p.git(APP, 'rev-parse', fork_ref),
             f'`{app.integration}` differs from `{fork_ref}`; push or pull first')

    pin = p.pinned_sdk()
    p.git(SDK, 'fetch', '--quiet', sdk.fork_remote)
    sdk_ref = f'{sdk.fork_remote}/{sdk.integration}'
    _require(p.git_ok(SDK, 'merge-base', '--is-ancestor', pin, sdk_ref),
             f'pinned SDK commit {pin[:10]} is not on `{sdk_ref}`; push the SDK first')
    _require(p.runner.run(['gh', 'auth', 'status'], check=False).returncode == 0,
             '`gh auth status` failed; run `gh auth login`')

    warnings = []
    for repo, rev in ((APP, 'HEAD'), (SDK, pin)):
        spec = p.spec(repo)
        p.git(repo, 'fetch', '--quiet', spec.upstream_remote)
        behind = int(p.git(repo, 'rev-list', '--count', f'{rev}..{p.upstream_main(repo)}'))
        if behind:
            warnings.append(f'{spec.name} is {behind} commit(s) behind upstream; consider `bin/personal sync`')
    return warnings


def release_notes(p: Project, pin: str, previous_tag) -> str:
    span = [f'{previous_tag}..HEAD'] if previous_tag else ['-n', '30', 'HEAD']
    merges = p.git(APP, 'log', '--merges', '--first-parent', '--format=- %s', *span)
    delta = p.git(SDK, 'diff', '--stat', p.upstream_main(SDK), pin)
    return '\n'.join([
        '## CrossInk merges', merges or '- (none since the previous release)', '',
        f'## freeink-sdk `{pin[:10]}` fork delta vs upstream', '```', delta or '(none)', '```', '',
    ])


def release(p: Project, out=print) -> str:
    for warning in check_guards(p):
        out(f'warning: {warning}')
    app = p.spec(APP)
    p.git(APP, 'fetch', '--quiet', '--tags', app.fork_remote)
    base = versioning.base_version(p.root)
    tags = p.git(APP, 'tag', '--list', 'v*').splitlines()
    n = versioning.next_build_number(tags, base)
    tag = versioning.release_tag(base, n)
    previous = versioning.latest_release_tag(tags)
    pin = p.pinned_sdk()

    out(f'Building {tag} ({PERSONAL_ENV}) ...')
    p.runner.run(['pio', 'run', '-e', PERSONAL_ENV], cwd=p.root,
                 env={'CROSSINK_PERSONAL_VERSION': f'{base}.{n}'}, stream=True)
    artifact = p.root / ARTIFACT
    _require(artifact.is_file(), f'build finished but {ARTIFACT} is missing')

    p.git(APP, 'tag', tag)
    p.git(APP, 'push', '--quiet', app.fork_remote, tag)
    with tempfile.NamedTemporaryFile('w', prefix='personal-notes-', suffix='.md', delete=False) as notes:
        notes.write(release_notes(p, pin, previous))
    command = ['gh', 'release', 'create', tag, str(artifact), '--repo', app.fork_slug,
               '--title', tag, '--notes-file', notes.name, '--latest']
    result = p.runner.run(command, check=False)
    if result.returncode != 0:
        raise PersonalError(f'tag {tag} is pushed but the upload failed: {result.stderr.strip()}\n'
                            f'retry with:\n  {shlex.join(command)}')
    out(f'Published {tag}. On the reader: Settings > Check for updates.')
    return tag
```

Update `cli.py` `dispatch` (replace the whole function):

```python
def dispatch(project: Project, args) -> None:
    if args.command == 'release':
        from . import release
        release.release(project)
        return
    raise PersonalError(f'`{args.command}` is not implemented yet')
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m unittest discover -s scripts/personal/tests -t scripts -v`
Expected: all versioning and release tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/personal
git commit -m "feat: add guarded OTA releases to bin/personal"
```

---

### Task 7: Device commands: `flash`, `monitor`, `logs`

**Files:**
- Create: `scripts/personal/device.py`, `scripts/personal/tests/test_device.py`
- Modify: `scripts/personal/cli.py` (`dispatch`)

**Interfaces:**
- Consumes: `Project`, `versioning.version_at_head`, `versioning.base_version`, `PERSONAL_ENV`, `DEBUG_ENV`.
- Produces: `device.WAKE_MESSAGE: str`, `device.select_port(candidates, choose=input) -> str`, `device.list_ports() -> list[str]`, `device.flash(p, debug=False, ports=None, choose=input) -> None`, `device.monitor_command(port, logfile, system) -> list[str]`, `device.monitor(p, ports=None, choose=input) -> None`, `device.find_log_volume(volumes_root: Path) -> Path`, `device.pull_logs(p, volumes_root=Path('/Volumes'), now=None) -> Path`.

- [ ] **Step 1: Write the failing tests** `scripts/personal/tests/test_device.py`:

```python
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from personal import device
from personal.proc import PersonalError, Result
from personal.project import Project
from personal.tests.fakes import FakeRunner


class SelectPortTest(unittest.TestCase):
    def test_ignores_bluetooth_and_uses_single_match(self):
        ports = ['/dev/cu.Bluetooth-Incoming-Port', '/dev/cu.usbmodem1101']
        self.assertEqual(device.select_port(ports), '/dev/cu.usbmodem1101')

    def test_no_port_tells_user_to_wake_reader(self):
        with self.assertRaises(PersonalError) as ctx:
            device.select_port(['/dev/cu.Bluetooth-Incoming-Port'])
        self.assertIn('wake the reader', str(ctx.exception))

    def test_several_ports_prompt(self):
        ports = ['/dev/cu.usbmodem2', '/dev/cu.usbmodem1']
        self.assertEqual(device.select_port(ports, choose=lambda _: '2'), '/dev/cu.usbmodem2')

    def test_invalid_choice_refuses(self):
        with self.assertRaises(PersonalError):
            device.select_port(['/dev/cu.usbmodem2', '/dev/cu.usbmodem1'], choose=lambda _: '9')


class FlashTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / 'platformio.ini').write_text('[crossink]\nversion = 1.6.0\n')
        self.runner = FakeRunner({('git', 'tag', '--points-at', 'HEAD'): Result(0, 'v1.6.0.4\nv1.6.0.3\n')})
        self.p = Project(root, self.runner)

    def pio_call(self):
        return [c for c in self.runner.calls if c['argv'][0] == 'pio'][0]

    def test_tagged_head_flashes_release_version(self):
        device.flash(self.p, ports=['/dev/cu.usbmodem1'])
        call = self.pio_call()
        self.assertEqual(call['argv'], ['pio', 'run', '-e', 'x4-pro-personal', '-t', 'upload',
                                        '--upload-port', '/dev/cu.usbmodem1'])
        self.assertEqual(call['env'], {'CROSSINK_PERSONAL_VERSION': '1.6.0.4'})

    def test_untagged_head_flashes_build_zero(self):
        self.runner.responses[('git', 'tag', '--points-at', 'HEAD')] = Result(0, '')
        device.flash(self.p, ports=['/dev/cu.usbmodem1'])
        self.assertIsNone(self.pio_call()['env'])

    def test_debug_flashes_debug_env(self):
        device.flash(self.p, debug=True, ports=['/dev/cu.usbmodem1'])
        self.assertIn('x4-pro-debug', self.pio_call()['argv'])


class MonitorCommandTest(unittest.TestCase):
    def test_macos_uses_bsd_script(self):
        cmd = device.monitor_command('/dev/cu.usbmodem1', Path('/tmp/s.log'), 'Darwin')
        self.assertEqual(cmd[:3], ['script', '-q', '/tmp/s.log'])
        self.assertIn('/dev/cu.usbmodem1', cmd)

    def test_linux_uses_util_linux_script(self):
        cmd = device.monitor_command('/dev/ttyACM0', Path('/tmp/s.log'), 'Linux')
        self.assertEqual(cmd[:3], ['script', '-q', '-c'])
        self.assertEqual(cmd[-1], '/tmp/s.log')


class LogPullTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.volumes = self.base / 'Volumes'
        (self.volumes / 'Macintosh HD').mkdir(parents=True)

    def make_reader_volume(self, name='CROSSINK'):
        vol = self.volumes / name
        (vol / '.crosspoint' / 'logs').mkdir(parents=True)
        (vol / '.crosspoint' / 'logs' / 'log.txt').write_text('boot\n')
        (vol / '.crosspoint' / 'logs' / 'log.1.txt').write_text('older\n')
        (vol / 'crash_report.txt').write_text('panic\n')
        return vol

    def test_no_reader_volume(self):
        with self.assertRaises(PersonalError) as ctx:
            device.find_log_volume(self.volumes)
        self.assertIn('USB Drive', str(ctx.exception))

    def test_two_reader_volumes_refuse(self):
        self.make_reader_volume('A')
        self.make_reader_volume('B')
        with self.assertRaises(PersonalError):
            device.find_log_volume(self.volumes)

    def test_pull_copies_logs_and_crash_report(self):
        self.make_reader_volume()
        p = Project(self.base / 'repo', FakeRunner())
        dest = device.pull_logs(p, self.volumes, now=datetime(2026, 9, 28, 12, 0, 0))
        self.assertEqual(dest, self.base / 'repo' / 'device-logs' / '20260928-120000')
        self.assertEqual(sorted(f.name for f in dest.iterdir()), ['crash_report.txt', 'log.1.txt', 'log.txt'])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest discover -s scripts/personal/tests -t scripts -p 'test_device.py' -v`
Expected: ERROR `cannot import name 'device' from 'personal'`.

- [ ] **Step 3: Implement** `scripts/personal/device.py`:

```python
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
```

Update `cli.py` `dispatch`, adding before the final `raise`:

```python
    if args.command in ('flash', 'monitor', 'logs'):
        from . import device
        if args.command == 'flash':
            device.flash(project, debug=args.debug)
        elif args.command == 'monitor':
            device.monitor(project)
        else:
            device.pull_logs(project)
        return
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest discover -s scripts/personal/tests -t scripts -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/personal
git commit -m "feat: add flash, monitor, and SD log pull to bin/personal"
```

---

### Task 8: Topic pairing, lifecycle, and `status`

**Files:**
- Create: `scripts/personal/topics.py`, `scripts/personal/status.py`, `scripts/personal/tests/test_topics.py`, `scripts/personal/tests/test_status.py`
- Modify: `scripts/personal/cli.py` (`dispatch`)

**Interfaces:**
- Consumes: `Project`, `APP`/`SDK`, `TOPIC_PREFIX`, `SDK_PATH`; fixture from Task 6.
- Produces:
  - `topics.State` enum (`FORK_ONLY`, `PR_OPEN`, `MERGED_UNSYNCED`, `RETIRED`, `CLOSED`), `topics.ACTIONS: dict[State, str]`, `topics.classify(pr: dict | None, merge_in_integration: bool) -> State`, `topics.find_pr(p, repo, topic) -> dict | None`, `topics.local_topics(p, repo) -> list[str]`, `topics.Pairing(pairs: dict[str, list[str]], unpaired_bumps: list[str])`, `topics.derive_pairs(p) -> Pairing`.
  - `status.report(p, fetch=True) -> list[str]`, `status.status(p, out=print) -> None`.

- [ ] **Step 1: Write the failing tests** `scripts/personal/tests/test_topics.py`:

```python
import json
import unittest

from personal import topics
from personal.proc import Result
from personal.project import APP, SDK, Project
from personal.tests.fakes import FakeRunner, ToolFake
from personal.tests.gitfixture import Fixture, git


class ClassifyTest(unittest.TestCase):
    def test_states(self):
        self.assertIs(topics.classify(None, False), topics.State.FORK_ONLY)
        self.assertIs(topics.classify({'state': 'OPEN'}, False), topics.State.PR_OPEN)
        self.assertIs(topics.classify({'state': 'MERGED'}, False), topics.State.MERGED_UNSYNCED)
        self.assertIs(topics.classify({'state': 'MERGED'}, True), topics.State.RETIRED)
        self.assertIs(topics.classify({'state': 'CLOSED'}, False), topics.State.CLOSED)

    def test_every_state_has_an_action(self):
        self.assertEqual(set(topics.ACTIONS), set(topics.State))


class FindPrTest(unittest.TestCase):
    def test_ignores_prs_from_other_owners_and_queries_upstream(self):
        prs = [{'number': 9, 'state': 'OPEN', 'headRepositoryOwner': {'login': 'someone'}},
               {'number': 7, 'state': 'MERGED', 'headRepositoryOwner': {'login': 'jtmcn'},
                'mergeCommit': {'oid': 'abc'}}]
        runner = FakeRunner({('gh', 'pr', 'list'): Result(0, json.dumps(prs))})
        pr = topics.find_pr(Project(None, runner), SDK, 'joel/x')
        self.assertEqual(pr['number'], 7)
        argv = runner.calls[0]['argv']
        self.assertIn('Free-Ink/freeink-sdk', argv)
        self.assertIn('joel/x', argv)

    def test_no_pr(self):
        runner = FakeRunner({('gh', 'pr', 'list'): Result(0, '[]')})
        self.assertIsNone(topics.find_pr(Project(None, runner), APP, 'joel/x'))


class DerivePairsTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)
        self.p = Project(self.fx.root, ToolFake())

    def test_bump_belongs_to_lowest_stacked_topic(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        self.fx.add_app_topic('joel/app-b', base='joel/app-a')
        pairing = topics.derive_pairs(self.p)
        self.assertEqual(pairing.pairs, {'joel/app-a': ['joel/sdk-a'], 'joel/app-b': []})
        self.assertEqual(pairing.unpaired_bumps, [])

    def test_pin_to_upstream_commit_is_not_a_pairing(self):
        self.fx.advance_sdk_upstream('up.txt', 'x\n')
        git(self.fx.sdk, 'fetch', '-q', 'origin')
        git(self.fx.sdk, 'checkout', '-q', 'origin/main')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        pairing = topics.derive_pairs(self.p)
        self.assertEqual(pairing.pairs, {'joel/app-a': []})
        self.assertEqual(pairing.unpaired_bumps, [])

    def test_pin_to_non_merge_commit_is_unpaired(self):
        self.fx.commit(self.fx.sdk, 'loose.txt', 'x\n', 'sdk: loose commit on crossink')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        self.assertEqual(len(topics.derive_pairs(self.p).unpaired_bumps), 1)


if __name__ == '__main__':
    unittest.main()
```

`scripts/personal/tests/test_status.py`:

```python
import json
import unittest

from personal import status
from personal.proc import Result
from personal.project import Project
from personal.tests.fakes import ToolFake
from personal.tests.gitfixture import Fixture, git


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)
        self.tools = ToolFake()
        self.p = Project(self.fx.root, self.tools)

    def text(self):
        return '\n'.join(status.report(self.p))

    def test_reports_pairs_states_and_delta(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        out = self.text()
        self.assertIn('joel/app-a', out)
        self.assertIn('<-> joel/sdk-a', out)
        self.assertIn('fork-only, no PR', out)
        self.assertIn('a.txt', out)
        self.assertIn('pin: matches crossink tip', out)

    def test_retired_topic_prints_delete_command(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        merged = git(self.fx.sdk, 'rev-parse', 'crossink')
        pr = [{'number': 3, 'state': 'MERGED', 'headRepositoryOwner': {'login': 'jtmcn'},
               'mergeCommit': {'oid': merged}}]
        self.tools.gh_responses[('gh', 'pr', 'list', '-R', 'Free-Ink/freeink-sdk', '--head', 'joel/sdk-a')] = \
            Result(0, json.dumps(pr))
        out = self.text()
        self.assertIn('retired', out)
        self.assertIn('branch -d joel/sdk-a', out)

    def test_fork_main_drift_is_flagged(self):
        self.fx.advance_sdk_upstream('up.txt', 'x\n')
        self.assertIn('0 ahead, 1 behind', self.text())

    def test_unpushed_and_unmerged_topics_are_flagged(self):
        git(self.fx.root, 'checkout', '-q', '-b', 'joel/local', 'upstream/main')
        self.fx.commit(self.fx.root, 'local.txt', 'x\n', 'feat: local only')
        git(self.fx.root, 'checkout', '-q', 'personal')
        out = self.text()
        self.assertIn('joel/local: not merged into personal, not pushed', out)

    def test_empty_sdk_delta_says_fork_not_needed(self):
        self.assertIn('SDK fork no longer needed', self.text())

    def test_status_reports_missing_integration_branch(self):
        git(self.fx.root, 'checkout', '-q', '--detach')
        git(self.fx.root, 'branch', '-D', 'personal')
        self.assertIn('`personal` branch missing', self.text())


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest discover -s scripts/personal/tests -t scripts -p 'test_[ts][ot]*.py' -v`
Expected: ERROR `cannot import name 'topics'` / `'status'`.

- [ ] **Step 3: Implement** `scripts/personal/topics.py`:

```python
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
```

`scripts/personal/status.py`:

```python
"""Combined status for the CrossInk + freeink-sdk fork pair."""

from __future__ import annotations

from . import topics
from .project import APP, SDK, Project


def _indent(text: str) -> list[str]:
    return ['    ' + line for line in text.splitlines()]


def _has_ref(p, repo, ref):
    return p.git_ok(repo, 'rev-parse', '--verify', '--quiet', ref)


def repo_lines(p: Project, repo: str) -> list[str]:
    spec, up = p.spec(repo), p.upstream_main(repo)
    lines = [f'== {spec.name} ==']
    ahead, behind = p.git(repo, 'rev-list', '--left-right', '--count', f'{spec.fork_remote}/main...{up}').split()
    drift = '' if ahead == behind == '0' else '  <- fork main should mirror upstream; `sync` fixes'
    lines.append(f'fork main vs upstream: {ahead} ahead, {behind} behind{drift}')
    if not _has_ref(p, repo, f'refs/heads/{spec.integration}'):
        lines.append(f'`{spec.integration}` branch missing')
        return lines
    lines.append(f'`{spec.integration}` behind upstream: '
                 f'{p.git(repo, "rev-list", "--count", f"{spec.integration}..{up}")} commit(s)')
    delta = p.git(repo, 'diff', '--stat', up, spec.integration)
    lines.append('fork delta:' if delta else 'fork delta: none')
    lines += _indent(delta)
    for topic in topics.local_topics(p, repo):
        notes = []
        if not p.git_ok(repo, 'merge-base', '--is-ancestor', topic, spec.integration):
            notes.append(f'not merged into {spec.integration}')
        remote = f'{spec.fork_remote}/{topic}'
        if not _has_ref(p, repo, remote) or p.git(repo, 'rev-parse', topic) != p.git(repo, 'rev-parse', remote):
            notes.append('not pushed')
        if notes:
            lines.append(f'  {topic}: ' + ', '.join(notes))
    return lines


def sdk_pin_lines(p: Project) -> list[str]:
    pin = p.pinned_sdk()
    if not pin:
        return ['pin: CrossInk HEAD has no freeink-sdk gitlink']
    tip = p.git(SDK, 'rev-parse', 'crossink', check=False)
    lines = [f'pin: matches crossink tip ({pin[:10]})' if pin == tip
             else f'pin: {pin[:10]} differs from crossink tip {tip[:10]}']
    if not p.git(SDK, 'diff', '--stat', p.upstream_main(SDK), pin):
        lines.append('SDK fork no longer needed: repin to Free-Ink and restore .gitmodules')
    return lines


def topic_lines(p: Project) -> list[str]:
    pairing = topics.derive_pairs(p)
    sdk_to_app = {s: a for a, sdks in pairing.pairs.items() for s in sdks}
    lines = ['== Topics ==']
    for repo in (APP, SDK):
        spec = p.spec(repo)
        for topic in topics.local_topics(p, repo):
            pr = topics.find_pr(p, repo, topic)
            oid = ((pr or {}).get('mergeCommit') or {}).get('oid')
            merged = bool(oid) and p.git_ok(repo, 'merge-base', '--is-ancestor', oid, spec.integration)
            state = topics.classify(pr, merged)
            pair = ', '.join(pairing.pairs.get(topic, [])) if repo == APP else sdk_to_app.get(topic, '')
            pair_text = f'<-> {pair}' if pair else ''
            lines.append(f'{spec.name:<12}{topic:<40}{state.value:<30}{pair_text:<44}{topics.ACTIONS[state]}')
            if state is topics.State.RETIRED:
                lines.append(f'    git -C {p.path(repo)} branch -d {topic} && '
                             f'git -C {p.path(repo)} push {spec.fork_remote} --delete {topic}')
    for commit in pairing.unpaired_bumps:
        lines.append(f'unpaired gitlink bump {commit[:10]}: pinned SDK commit is not a crossink topic merge')
    return lines


def report(p: Project, fetch: bool = True) -> list[str]:
    if fetch:
        for repo in (APP, SDK):
            spec = p.spec(repo)
            p.git(repo, 'fetch', '--quiet', spec.upstream_remote)
            p.git(repo, 'fetch', '--quiet', spec.fork_remote)
    return repo_lines(p, APP) + [''] + repo_lines(p, SDK) + sdk_pin_lines(p) + [''] + topic_lines(p)


def status(p: Project, out=print) -> None:
    for line in report(p):
        out(line)
```

Update `cli.py` `dispatch`, adding before the final `raise`:

```python
    if args.command == 'status':
        from . import status
        status.status(project)
        return
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest discover -s scripts/personal/tests -t scripts -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/personal
git commit -m "feat: add two-fork status with topic pairing and PR lifecycle"
```

---

### Task 9: `sync`

**Files:**
- Create: `scripts/personal/sync.py`, `scripts/personal/tests/test_sync.py`
- Modify: `scripts/personal/cli.py` (`dispatch`)

**Interfaces:**
- Consumes: `Project`, `SYNC_BUILD_ENVS`, `SDK_PATH`, `status.status`; fixture, `ToolFake`.
- Produces: `sync.sync(p, out=print) -> None`.

- [ ] **Step 1: Write the failing tests** `scripts/personal/tests/test_sync.py`:

```python
import unittest

from personal import sync
from personal.proc import PersonalError
from personal.project import Project
from personal.tests.fakes import ToolFake
from personal.tests.gitfixture import Fixture, git


def quiet(*_):
    pass


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.cleanup)
        self.tools = ToolFake()
        self.p = Project(self.fx.root, self.tools)

    def fork_refs(self):
        return (self.fx.remote_sha(self.fx.sdk_fork, 'crossink'), self.fx.remote_sha(self.fx.app_fork, 'personal'))

    def test_sync_merges_both_upstreams_builds_and_pushes(self):
        sdk_up = self.fx.advance_sdk_upstream('up.txt', 'x\n')
        self.fx.advance_app_upstream('app-up.txt', 'x\n')
        sync.sync(self.p, out=quiet)
        fork_crossink, fork_personal = self.fork_refs()
        git(self.fx.sdk_fork, 'merge-base', '--is-ancestor', sdk_up, fork_crossink)
        self.assertEqual(self.fx.remote_sha(self.fx.sdk_fork, 'main'), sdk_up)
        self.assertEqual(self.fx.remote_sha(self.fx.app_fork, 'main'), self.fx.remote_sha(self.fx.app_upstream, 'main'))
        pinned = git(self.fx.app_fork, 'ls-tree', fork_personal, 'freeink-sdk').split()[2]
        self.assertEqual(pinned, fork_crossink)
        self.assertEqual([c[3] for c in self.tools.tool_calls('pio')], ['x4-pro-personal', 'default', 'simulator'])

    def test_sync_build_failure_pushes_nothing(self):
        self.fx.advance_sdk_upstream('up.txt', 'x\n')
        before = self.fork_refs()
        self.tools.fail_envs.add('default')
        with self.assertRaises(PersonalError):
            sync.sync(self.p, out=quiet)
        self.assertEqual(self.fork_refs(), before)

    def test_sync_sdk_conflict_stops_before_push(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'lib.txt', 'ours\n')
        self.fx.advance_sdk_upstream('lib.txt', 'theirs\n')
        before = self.fork_refs()
        with self.assertRaises(PersonalError) as ctx:
            sync.sync(self.p, out=quiet)
        self.assertIn('lib.txt', str(ctx.exception))
        self.assertIn('rerun `bin/personal sync`', str(ctx.exception))
        self.assertEqual(self.fork_refs(), before)
        self.assertEqual(self.tools.tool_calls('pio'), [])

    def test_sync_resumes_after_resolved_sdk_conflict(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'lib.txt', 'ours\n')
        self.fx.advance_sdk_upstream('lib.txt', 'theirs\n')
        with self.assertRaises(PersonalError):
            sync.sync(self.p, out=quiet)
        (self.fx.sdk / 'lib.txt').write_text('resolved\n')
        git(self.fx.sdk, 'add', 'lib.txt')
        git(self.fx.sdk, 'commit', '-q', '--no-edit')
        sync.sync(self.p, out=quiet)
        fork_crossink, fork_personal = self.fork_refs()
        self.assertEqual(git(self.fx.app_fork, 'ls-tree', fork_personal, 'freeink-sdk').split()[2], fork_crossink)

    def test_sync_resolves_upstream_gitlink_bump(self):
        self.fx.add_sdk_topic('joel/sdk-a', 'a.txt')
        sdk_up = self.fx.advance_sdk_upstream('up.txt', 'x\n')
        self.fx.add_app_topic('joel/app-a', bump_sdk=True)
        self.fx.advance_app_upstream('app-up.txt', 'x\n', pin_sdk=sdk_up)
        sync.sync(self.p, out=quiet)
        fork_crossink, fork_personal = self.fork_refs()
        self.assertEqual(git(self.fx.app_fork, 'ls-tree', fork_personal, 'freeink-sdk').split()[2], fork_crossink)

    def test_sync_refuses_off_personal(self):
        git(self.fx.root, 'checkout', '-q', '-b', 'joel/elsewhere')
        with self.assertRaises(PersonalError) as ctx:
            sync.sync(self.p, out=quiet)
        self.assertIn('sync runs on `personal`', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
```

Note for `test_sync_resolves_upstream_gitlink_bump`: the SDK topic moves `crossink` so the app topic has a pin to commit; upstream CrossInk pins a newer Free-Ink commit, so both sides changed the gitlink and the merge conflicts only on `freeink-sdk`; after the SDK step `crossink` contains upstream SDK main, so auto-resolution applies.

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest discover -s scripts/personal/tests -t scripts -p 'test_sync.py' -v`
Expected: ERROR `cannot import name 'sync'`.

- [ ] **Step 3: Implement** `scripts/personal/sync.py`:

```python
"""Catch both forks up with their upstreams, build, then push SDK before CrossInk."""

from __future__ import annotations

from .proc import PersonalError
from .project import APP, SDK, SDK_PATH, SYNC_BUILD_ENVS, Project


def _require_no_merge_in_progress(p: Project, repo: str) -> None:
    if p.git_ok(repo, 'rev-parse', '--verify', '--quiet', 'MERGE_HEAD'):
        raise PersonalError(f'{p.spec(repo).name} has a merge in progress in {p.path(repo)}; '
                            'finish it with `git commit` (or abort it), then rerun `bin/personal sync`')


def _require_clean(p: Project) -> None:
    # A moved SDK checkout is expected when resuming, so the gitlink line is allowed.
    app_dirty = [line for line in p.git(APP, 'status', '--porcelain', '--untracked-files=no').splitlines()
                 if not line.endswith(f' {SDK_PATH}')]
    if app_dirty:
        raise PersonalError('CrossInk has uncommitted changes:\n' + '\n'.join(app_dirty))
    sdk_dirty = p.git(SDK, 'status', '--porcelain', '--untracked-files=no')
    if sdk_dirty:
        raise PersonalError(f'{SDK_PATH} has uncommitted changes:\n{sdk_dirty}')


def _resolve_gitlink_conflict(p: Project) -> None:
    theirs = p.git(APP, 'rev-parse', f'MERGE_HEAD:{SDK_PATH}')
    ours = p.git(SDK, 'rev-parse', 'HEAD')
    if not p.git_ok(SDK, 'merge-base', '--is-ancestor', theirs, ours):
        raise PersonalError(f'upstream CrossInk pins SDK {theirs[:10]}, which `crossink` does not contain; '
                            f'merge it into crossink, then `git add {SDK_PATH} && git commit` and rerun sync')
    p.git(APP, 'add', SDK_PATH)
    p.git(APP, 'commit', '--quiet', '--no-edit')


def _merge_upstream(p: Project, repo: str, out) -> None:
    spec, upstream = p.spec(repo), p.upstream_main(repo)
    if p.git_ok(repo, 'merge-base', '--is-ancestor', upstream, 'HEAD'):
        out(f'{spec.name}: `{spec.integration}` already contains {upstream}')
        return
    merged = p.runner.run(['git', 'merge', '--no-ff', '--no-edit', upstream], cwd=p.path(repo), check=False)
    if merged.returncode == 0:
        return
    conflicted = p.git(repo, 'diff', '--name-only', '--diff-filter=U').splitlines()
    if repo == APP and conflicted == [SDK_PATH]:
        _resolve_gitlink_conflict(p)
        return
    files = '\n'.join(f'  {name}' for name in conflicted) or '  (see `git status`)'
    raise PersonalError(f'{spec.name}: merging {upstream} into `{spec.integration}` conflicted in:\n{files}\n'
                        f'resolve in {p.path(repo)}, `git commit`, then rerun `bin/personal sync`')


def sync(p: Project, out=print) -> None:
    app, sdk = p.spec(APP), p.spec(SDK)
    branch = p.git(APP, 'rev-parse', '--abbrev-ref', 'HEAD')
    if branch != app.integration:
        raise PersonalError(f'sync runs on `{app.integration}`, not `{branch}`')
    for repo in (APP, SDK):
        _require_no_merge_in_progress(p, repo)
    _require_clean(p)

    for repo in (SDK, APP):
        spec = p.spec(repo)
        p.git(repo, 'fetch', '--quiet', spec.upstream_remote)
        p.git(repo, 'fetch', '--quiet', spec.fork_remote)
        # Fast-forward only: a diverged fork main fails here instead of being overwritten.
        p.git(repo, 'push', '--quiet', spec.fork_remote, f'{p.upstream_main(repo)}:refs/heads/main')
        if repo == SDK:
            p.git(SDK, 'checkout', '--quiet', sdk.integration)
        _merge_upstream(p, repo, out)

    tip = p.git(SDK, 'rev-parse', 'HEAD')
    if p.pinned_sdk() != tip:
        p.git(APP, 'add', SDK_PATH)
        p.git(APP, 'commit', '--quiet', '-m', f'chore: sync freeink-sdk crossink to {tip[:10]}')

    for env in SYNC_BUILD_ENVS:
        out(f'Building {env} ...')
        p.runner.run(['pio', 'run', '-e', env], cwd=p.root, stream=True)

    p.git(SDK, 'push', '--quiet', sdk.fork_remote, sdk.integration)
    p.git(APP, 'push', '--quiet', app.fork_remote, app.integration)
    from . import status
    status.status(p, out=out)
```

Update `cli.py` `dispatch`, adding before the final `raise`:

```python
    if args.command == 'sync':
        from . import sync
        sync.sync(project)
        return
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m unittest discover -s scripts/personal/tests -t scripts -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/personal
git commit -m "feat: add two-fork upstream sync to bin/personal"
```

---

### Task 10: `setup`, docs, and context

**Files:**
- Create: `scripts/personal/setup_cmd.py`, `scripts/personal/tests/test_setup.py`, `docs/development/personal-builds.md`
- Modify: `scripts/personal/cli.py` (`dispatch`), `.claude/CONTEXT.md`
- Memory (outside repo): `/Users/jm/.claude/projects/-Users-jm-Code-third-party-CrossInk/memory/fork-firmware-setup.md`

**Interfaces:**
- Consumes: `Project`, `APP_SPEC`/`SDK_SPEC`.
- Produces: `setup_cmd.GIT_CONFIG: tuple[tuple[str, str], ...]`, `setup_cmd.setup(p, out=print) -> None`.

- [ ] **Step 1: Write the failing test** `scripts/personal/tests/test_setup.py`. Both repos have an `origin`, so the fake answers `git remote get-url` per repo (by `cwd`):

```python
import unittest
from pathlib import Path

from personal import setup_cmd
from personal.proc import PersonalError, Result
from personal.project import Project
from personal.tests.fakes import FakeRunner

APP_REMOTES = {'upstream': 'git@github.com:uxjulia/CrossInk.git', 'origin': 'git@github.com:jtmcn/CrossInk.git'}
SDK_REMOTES = {'origin': 'https://github.com/Free-Ink/freeink-sdk.git',
               'fork': 'https://github.com/jtmcn/freeink-sdk.git'}


class CwdRunner(FakeRunner):
    def __init__(self, app, sdk):
        super().__init__()
        self.tables = {'app': dict(app), 'sdk': dict(sdk)}

    def run(self, argv, cwd=None, env=None, check=True, stream=False):
        argv = [str(a) for a in argv]
        if argv[:3] != ['git', 'remote', 'get-url']:
            return super().run(argv, cwd, env, check, stream)
        self.calls.append({'argv': argv, 'cwd': cwd, 'env': env})
        table = self.tables['sdk' if str(cwd).endswith('freeink-sdk') else 'app']
        url = table.get(argv[3])
        result = Result(0, url + '\n') if url else Result(2, '', 'No such remote')
        if check and result.returncode:
            raise PersonalError('missing remote')
        return result


def project(app=APP_REMOTES, sdk=SDK_REMOTES):
    runner = CwdRunner(app, sdk)
    return Project(Path('/r'), runner), runner


class SetupTest(unittest.TestCase):
    def test_sets_git_config_in_crossink_only(self):
        p, runner = project()
        setup_cmd.setup(p, out=lambda *_: None)
        configs = [(c['argv'][2:], c['cwd']) for c in runner.calls if c['argv'][:2] == ['git', 'config']]
        self.assertIn((['push.recurseSubmodules', 'check'], Path('/r')), configs)
        self.assertIn((['diff.submodule', 'log'], Path('/r')), configs)
        self.assertIn((['status.submoduleSummary', 'true'], Path('/r')), configs)
        self.assertNotIn('submodule.recurse', [argv[0] for argv, _ in configs])

    def test_adds_missing_remote(self):
        p, runner = project(sdk={'origin': SDK_REMOTES['origin']})
        setup_cmd.setup(p, out=lambda *_: None)
        self.assertIn(['git', 'remote', 'add', 'fork', 'https://github.com/jtmcn/freeink-sdk.git'],
                      [c['argv'] for c in runner.calls])

    def test_refuses_wrong_remote(self):
        p, _ = project(app={**APP_REMOTES, 'upstream': 'git@github.com:someone/CrossInk.git'})
        with self.assertRaises(PersonalError) as ctx:
            setup_cmd.setup(p, out=lambda *_: None)
        self.assertIn('uxjulia/CrossInk', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest discover -s scripts/personal/tests -t scripts -p 'test_setup.py' -v`
Expected: ERROR `cannot import name 'setup_cmd'`.

- [ ] **Step 3: Implement** `scripts/personal/setup_cmd.py`:

```python
"""Wire the CrossInk + freeink-sdk checkouts so they behave as one project."""

from __future__ import annotations

from .proc import PersonalError
from .project import APP, SDK, Project

# submodule.recurse is deliberately absent: it detaches the SDK checkout on every branch switch.
GIT_CONFIG = (
    ('push.recurseSubmodules', 'check'),
    ('diff.submodule', 'log'),
    ('status.submoduleSummary', 'true'),
)


def setup(p: Project, out=print) -> None:
    for repo in (APP, SDK):
        spec = p.spec(repo)
        for remote, slug in ((spec.upstream_remote, spec.upstream_slug), (spec.fork_remote, spec.fork_slug)):
            url = p.git(repo, 'remote', 'get-url', remote, check=False)
            if not url:
                p.git(repo, 'remote', 'add', remote, f'https://github.com/{slug}.git')
                out(f'{spec.name}: added remote `{remote}` -> {slug}')
            elif slug.lower() not in url.lower():
                raise PersonalError(f'{spec.name} remote `{remote}` is {url}, expected {slug}')
    for key, value in GIT_CONFIG:
        p.git(APP, 'config', key, value)
    out('git config set: ' + ', '.join(f'{k}={v}' for k, v in GIT_CONFIG))
```

Update `cli.py` `dispatch`, adding before the final `raise`:

```python
    if args.command == 'setup':
        from . import setup_cmd
        setup_cmd.setup(project)
        return
```

- [ ] **Step 4: Run all tests**

Run: `python3 -m unittest discover -s scripts/personal/tests -t scripts -v && python3 scripts/test_git_branch_personal.py`
Expected: all PASS. `bin/personal <anything>` no longer reports "not implemented" for any of the 7 commands.

- [ ] **Step 5: Write** `docs/development/personal-builds.md`:

````markdown
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
````

- [ ] **Step 6: Point to it** — append to `.claude/CONTEXT.md` under `## Misc Repo Gotchas`:

```markdown
- Personal fork builds, OTA releases, SD logs, and the two-fork sync live behind `bin/personal`; see `docs/development/personal-builds.md`.
```

- [ ] **Step 7: Commit**

```bash
git add scripts/personal docs/development/personal-builds.md .claude/CONTEXT.md
git commit -m "docs: document personal builds and add bin/personal setup"
```

- [ ] **Step 8: Update memory** — in `fork-firmware-setup.md`, replace the paragraph starting `As of 2026-09-28 the user wants` with: `As of 2026-09-28 the two forks are operated as one project through bin/personal (setup/status/sync/release/flash/monitor/logs); integration branches personal (CrossInk) and crossink (SDK); OTA tags v<base>.<N> on jtmcn/CrossInk. See docs/development/personal-builds.md.` (Not a repo change; no commit.)

---

### Task 11: Rollout (outward-facing — confirm with the user before each push)

**Files:** none new; git operations on both repos and GitHub.

Every step that pushes, tags, publishes, or deletes must be confirmed with the user at the time it runs.

- [ ] **Step 1: Full verification before rollout**

Run: `cmake --build build/test -j && ctest --test-dir build/test --output-on-failure -j && python3 -m unittest discover -s scripts/personal/tests -t scripts && python3 scripts/test_git_branch_personal.py && pio run -e x4-pro-personal && pio run -e x4-pro && pio run -e default && pio run -e simulator`
Expected: everything passes.

- [ ] **Step 2: Push the topic** (confirm): `git push -u origin joel/personal-build-system`

- [ ] **Step 3: Create `personal`** (confirm before pushing):

```bash
git fetch upstream origin
git switch -c personal upstream/main
git merge --no-ff joel/x4pro-aa-overlap-settle -m "Merge branch 'joel/x4pro-aa-overlap-settle' into personal"
git merge --no-ff joel/personal-build-system -m "Merge branch 'joel/personal-build-system' into personal"
git submodule status freeink-sdk   # must show the crossink pin 447c7a3 with no leading '+'
git -C freeink-sdk switch crossink
git push -u origin personal
```

The stack top `joel/x4pro-aa-overlap-settle` carries the lower stacked topics and the fork `.gitmodules`.

- [ ] **Step 4: `bin/personal setup`**, then `bin/personal status`. Expected: three pairs as in spec §1b, every topic `fork-only, no PR`, SDK `crossink` 35 behind, SDK fork `main` 1 behind.

- [ ] **Step 5: First `bin/personal sync`** (confirm; it pushes both forks). Expected stop point: the build step fails on the upstream `local` variable vs PNGdec `#define local static` in `SleepActivity.cpp`. Fix on `personal` with a CrossInk-side commit (e.g. `#undef local` after the PNGdec include in `src/activities/boot_sleep/SleepActivity.cpp`, then build `x4-pro-personal`), commit `fix: undefine PNGdec's local macro before FreeInkUI media headers`, rerun `bin/personal sync`. Expected end: status shows zero drift and `pin: matches crossink tip`.

- [ ] **Step 6: First release** (confirm): `bin/personal release` → `v1.6.0.1`, then `bin/personal flash` with the reader awake. Settings > System shows `1.6.0.1-x4-pro`.

- [ ] **Step 7: Hardware checks** (spec §3 steps 2–6; the user runs these):
  - Read ~10 minutes, sleep, wake; USB Drive; `bin/personal logs`. Expect one `=== boot` line per wake, `ERR` lines present, and note KB/hour.
  - Start USB Drive mid-session, eject, stop; confirm the card mounts cleanly and new lines follow.
  - Publish `v1.6.0.2` (any small change merged to `personal`); Check for updates offers it and installs.
  - `bin/personal flash --debug`; Check for updates offers `v1.6.0.2`.
  - Watchdog tail check: on a scratch branch only, add a temporary `while (true) {}` behind a debug-only chord, flash, trigger it, and confirm the next log contains `--- last lines before reset ---`. Do not merge that change.
