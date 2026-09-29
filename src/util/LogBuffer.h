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
