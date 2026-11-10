add_executable(BookmarkStoreTest
  BookmarkStoreTest.cpp
  ${REPO_ROOT}/src/BookmarkStore.cpp
  ${REPO_ROOT}/lib/uzlib/src/uzlib_checksums.c
)

target_include_directories(BookmarkStoreTest PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/stubs
  ${REPO_ROOT}/src
  ${REPO_ROOT}/lib/Serialization
  ${REPO_ROOT}/lib/uzlib/src
)

target_link_libraries(BookmarkStoreTest PRIVATE
  crosspoint_test_common
  GTest::gtest_main
)

gtest_discover_tests(BookmarkStoreTest)
