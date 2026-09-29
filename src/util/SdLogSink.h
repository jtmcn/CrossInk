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
