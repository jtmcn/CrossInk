#pragma once

#include <Arduino.h>

#include <algorithm>
#include <cstring>
#include <map>
#include <string>
#include <vector>

class HalStorage;

// In-memory file: reads from a snapshot, writes land in the store on close().
class HalFile {
 public:
  HalFile() = default;
  int read(void* output, size_t length) {
    const size_t count = std::min(length, content.size() - position);
    memcpy(output, content.data() + position, count);
    position += count;
    return static_cast<int>(count);
  }
  size_t write(const uint8_t* data, size_t length) {
    content.append(reinterpret_cast<const char*>(data), length);
    return length;
  }
  int available() const { return static_cast<int>(content.size() - position); }
  void close();

 private:
  friend class HalStorage;
  std::string content;
  size_t position = 0;
  std::string writePath;
};

using FsFile = HalFile;

class HalStorage {
 public:
  std::map<std::string, std::string> files;

  bool mkdir(const char*, bool = true) { return true; }
  bool exists(const char* path) const { return files.contains(path); }
  bool remove(const char* path) { return files.erase(path) > 0; }
  bool rename(const char* from, const char* to) {
    const auto source = files.find(from);
    if (source == files.end() || files.contains(to)) return false;
    files[to] = source->second;
    files.erase(source);
    return true;
  }
  std::vector<String> listFiles(const char* dir = "/", int = 200) const {
    std::vector<String> out;
    const std::string prefix = std::string(dir) + "/";
    for (const auto& [path, _] : files) {
      if (path.rfind(prefix, 0) == 0 && path.find('/', prefix.size()) == std::string::npos) {
        out.emplace_back(path.substr(prefix.size()));
      }
    }
    return out;
  }
  bool openFileForRead(const char*, const std::string& path, HalFile& file) const {
    const auto it = files.find(path);
    if (it == files.end()) return false;
    file = HalFile();
    file.content = it->second;
    return true;
  }
  bool openFileForWrite(const char*, const std::string& path, HalFile& file) {
    file = HalFile();
    file.writePath = path;
    return true;
  }
};

inline HalStorage Storage;

inline void HalFile::close() {
  if (!writePath.empty()) Storage.files[writePath] = content;
  writePath.clear();
  content.clear();
  position = 0;
}
