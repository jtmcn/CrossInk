#include "BookLoadingFeedback.h"

#include <Arduino.h>
#include <GfxRenderer.h>
#include <I18n.h>
#include <Logging.h>

#include "components/UITheme.h"

void BookLoadingFeedback::start() {
  startedAt = millis();
  pending = true;
}

bool BookLoadingFeedback::showIfPending(GfxRenderer& renderer) {
  if (!renderer.hasFrameBuffer() || !pending) return false;
  const auto elapsed = static_cast<uint32_t>(millis() - startedAt);
  if (elapsed < DELAY_MS) return false;
  finish();
  LOG_DBG("READER", "Loading notice after %u ms", static_cast<unsigned>(elapsed));
  // A prior notice may have a different size or orientation. Replace its pixels.
  renderer.clearScreen();
  GUI.drawPopup(renderer, tr(STR_LOADING));
  return true;
}

void BookLoadingFeedback::showIndexing(GfxRenderer& renderer) {
  finish();
  if (!renderer.hasFrameBuffer()) return;
  renderer.clearScreen();
  GUI.drawPopup(renderer, tr(STR_INDEXING));
}
