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
