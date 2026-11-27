#pragma once

#include <cstdint>

class GfxRenderer;

// Passed by value through the loader/reader handoff. Check only between loading
// stages, while the framebuffer is available and before painting page contents.
class BookLoadingFeedback {
  uint32_t startedAt = 0;
  bool pending = false;

 public:
  // Cached X4 Pro opens load the first page ~0.65 s after start (2.0 SD logs).
  static constexpr uint32_t DELAY_MS = 1000;

  void start();
  void finish() { pending = false; }
  bool showIfPending(GfxRenderer& renderer);
  void showIndexing(GfxRenderer& renderer);
};
