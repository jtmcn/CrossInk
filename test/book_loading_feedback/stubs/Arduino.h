#pragma once
#include <cstdint>
// 32-bit like the device, so the wrap test exercises the real overflow.
inline uint32_t fakeMillis = 0;
inline unsigned long millis() { return fakeMillis; }
