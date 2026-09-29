add_executable(LogBufferTest LogBufferTest.cpp)
target_link_libraries(LogBufferTest PRIVATE crosspoint_test_common GTest::gtest_main)
gtest_discover_tests(LogBufferTest PROPERTIES ENVIRONMENT "UBSAN_OPTIONS=halt_on_error=1")
