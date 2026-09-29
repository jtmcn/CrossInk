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
