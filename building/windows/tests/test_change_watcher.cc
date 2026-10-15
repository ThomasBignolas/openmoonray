// SPDX-License-Identifier: Apache-2.0
#include "application/ChangeWatcher.h"
#include <windows.h>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <future>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <thread>
namespace fs = std::filesystem;
using namespace std::chrono_literals;
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
std::string utf8(const fs::path& path) { auto text = path.u8string(); return {text.begin(), text.end()}; }
void write(const fs::path& path, const char* text) { std::ofstream(path, std::ios::binary) << text; }
int main()
{
    const auto directory = fs::temp_directory_path() / (L"moonray watcher \u00e9 " + std::to_wstring(GetCurrentProcessId()));
    try {
        fs::create_directory(directory);
        const auto file = directory / L"sc\u00e8ne.rdla";
        const auto temporary = directory / "swap.rdla";
        write(file, "initial");
        auto watcher = std::unique_ptr<moonray::ChangeWatcher>(moonray::ChangeWatcher::CreateChangeWatcher());
        watcher->watchFile(utf8(file));
        require(!watcher->hasChanged(), "registration should not signal change");
        auto changed = [&] {
            std::set<std::string> files;
            const auto deadline = std::chrono::steady_clock::now() + 3s;
            while (!watcher->hasChanged(&files) && std::chrono::steady_clock::now() < deadline) std::this_thread::sleep_for(5ms);
            require(files.count(utf8(file)) == 1, "notification keeps original UTF-8 filename");
            while (watcher->hasChanged()) {}
        };
        write(file, "modified");
        changed();
        write(temporary, "replacement");
        std::this_thread::sleep_for(30ms);
        require(!watcher->hasChanged(), "unwatched filename is filtered");
        require(MoveFileExW(temporary.c_str(), file.c_str(), MOVEFILE_REPLACE_EXISTING) != 0, "atomic replacement");
        changed();
        fs::remove(file);
        changed();
        write(file, "recreated");
        changed();
        auto waiting = std::async(std::launch::async, [&] { watcher->waitForChange(); });
        require(waiting.wait_for(40ms) == std::future_status::timeout, "wait blocks without a change");
        write(file, "wake up");
        require(waiting.wait_for(3s) == std::future_status::ready, "wait wakes after a change");
        waiting.get();
        watcher.reset();
        fs::remove(file);
        fs::remove(directory);
        std::cout << "File watcher: UTF-8, modify, replace, delete, recreate, filtering, blocking wait passed\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
