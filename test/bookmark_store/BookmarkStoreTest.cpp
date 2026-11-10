#include <HalStorage.h>
#include <gtest/gtest.h>

#include <cstring>
#include <string>

#include "BookmarkStore.h"

namespace {
constexpr int kPages = 100;
constexpr char kBookPath[] = "/Books/test.epub";

float pageProgress(int page) { return static_cast<float>(page) / kPages; }

class BookmarkStoreTest : public ::testing::Test {
 protected:
  void SetUp() override {
    Storage.files.clear();
    BOOKMARKS.unload();
    reload();
  }
  void TearDown() override { BOOKMARKS.unload(); }

  static void reload() {
    BOOKMARKS.unload();
    ASSERT_TRUE(BOOKMARKS.loadForBook(kBookPath, "Title", "Author", "epub"));
  }
  static bool addAuto(int page) { return BOOKMARKS.addAutoBookmark(0, pageProgress(page), kPages, "Ch", UINT16_MAX); }
  static void addManual(int page) { BOOKMARKS.addBookmark(0, pageProgress(page), kPages, "Ch"); }
  static size_t autoCount() {
    size_t n = 0;
    for (const auto& b : BOOKMARKS.getBookmarks()) n += b.isAuto ? 1 : 0;
    return n;
  }
};

TEST_F(BookmarkStoreTest, AutoBookmarkPersistsItsFlag) {
  ASSERT_TRUE(addAuto(5));
  addManual(9);
  reload();
  const auto& bms = BOOKMARKS.getBookmarks();
  ASSERT_EQ(bms.size(), 2u);
  EXPECT_TRUE(bms[0].isAuto);
  EXPECT_FALSE(bms[1].isAuto);
}

TEST_F(BookmarkStoreTest, SleepingAgainOnSamePageAddsNothing) {
  ASSERT_TRUE(addAuto(5));
  EXPECT_FALSE(addAuto(5));
  EXPECT_EQ(BOOKMARKS.getBookmarks().size(), 1u);
}

TEST_F(BookmarkStoreTest, ManualBookmarkOnPageSuppressesAuto) {
  addManual(5);
  EXPECT_FALSE(addAuto(5));
  ASSERT_EQ(BOOKMARKS.getBookmarks().size(), 1u);
  EXPECT_FALSE(BOOKMARKS.getBookmarks()[0].isAuto);
}

TEST_F(BookmarkStoreTest, AutoBookmarksDoNotDrivePageIndicatorOrRemoval) {
  ASSERT_TRUE(addAuto(5));
  EXPECT_FALSE(BOOKMARKS.hasBookmarkForPage(0, pageProgress(5), kPages));
  BOOKMARKS.removeBookmarkForPage(0, pageProgress(5), kPages);
  EXPECT_EQ(BOOKMARKS.getBookmarks().size(), 1u);
}

TEST_F(BookmarkStoreTest, ManualToggleConvertsAutoOnSamePage) {
  ASSERT_TRUE(addAuto(5));
  addManual(5);
  ASSERT_EQ(BOOKMARKS.getBookmarks().size(), 1u);
  EXPECT_FALSE(BOOKMARKS.getBookmarks()[0].isAuto);
}

TEST_F(BookmarkStoreTest, TrailKeepsNewestTenAndLeavesManualAlone) {
  addManual(99);
  for (int page = 0; page < 12; ++page) ASSERT_TRUE(addAuto(page));
  EXPECT_EQ(autoCount(), BookmarkStore::MAX_AUTO_BOOKMARKS);
  const auto& bms = BOOKMARKS.getBookmarks();
  ASSERT_EQ(bms.size(), BookmarkStore::MAX_AUTO_BOOKMARKS + 1);
  EXPECT_FALSE(bms[0].isAuto);
  EXPECT_FLOAT_EQ(bms[1].progress, pageProgress(2));  // pages 0 and 1 aged out
  EXPECT_FLOAT_EQ(bms.back().progress, pageProgress(11));
}

TEST_F(BookmarkStoreTest, ReturningToAnOlderStopMovesItToNewest) {
  ASSERT_TRUE(addAuto(5));
  ASSERT_TRUE(addAuto(8));
  ASSERT_TRUE(addAuto(5));
  const auto& bms = BOOKMARKS.getBookmarks();
  ASSERT_EQ(bms.size(), 2u);
  EXPECT_FLOAT_EQ(bms[0].progress, pageProgress(8));
  EXPECT_FLOAT_EQ(bms[1].progress, pageProgress(5));
}

template <typename T>
void appendPod(std::string& out, const T& value) {
  out.append(reinterpret_cast<const char*>(&value), sizeof(T));
}

void appendString(std::string& out, const std::string& s) {
  appendPod(out, static_cast<uint32_t>(s.size()));
  out += s;
}

TEST_F(BookmarkStoreTest, MigratesVersion5FileAsManualBookmarks) {
  addManual(3);  // creates the per-book file so we know its path
  ASSERT_EQ(Storage.files.size(), 1u);
  const std::string path = Storage.files.begin()->first;

  std::string v5;
  appendPod(v5, static_cast<uint8_t>(5));
  appendPod(v5, static_cast<uint16_t>(1));
  appendString(v5, "Title");
  appendString(v5, "Author");
  appendString(v5, kBookPath);
  appendPod(v5, static_cast<uint16_t>(0));
  appendPod(v5, pageProgress(3));
  appendPod(v5, static_cast<uint32_t>(0));
  char title[BOOKMARK_CHAPTER_TITLE_MAX] = "Ch";
  v5.append(title, sizeof(title));
  appendPod(v5, static_cast<uint16_t>(UINT16_MAX));
  char snippet[BOOKMARK_SNIPPET_MAX] = "text";
  v5.append(snippet, sizeof(snippet));
  Storage.files[path] = v5;

  reload();
  ASSERT_EQ(BOOKMARKS.getBookmarks().size(), 1u);
  EXPECT_FALSE(BOOKMARKS.getBookmarks()[0].isAuto);
  EXPECT_STREQ(BOOKMARKS.getBookmarks()[0].snippet, "text");
  EXPECT_EQ(static_cast<uint8_t>(Storage.files[path][0]), 6);  // rewritten on load
}
}  // namespace
