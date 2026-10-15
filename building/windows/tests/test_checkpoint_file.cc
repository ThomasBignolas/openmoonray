// SPDX-License-Identifier: Apache-2.0
#include "rendering/rndr/CheckpointFileWindows.h"
#include <fstream>
#include <future>
#include <iostream>
#include <stdexcept>

namespace fs = std::filesystem;
namespace checkpoint = moonray::rndr::checkpoint_file;
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
std::string utf8(const fs::path& path) { const auto text = path.u8string(); return {text.begin(), text.end()}; }
std::string read(const fs::path& path) {
    std::ifstream file(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}
void write(const fs::path& path, const std::string& bytes) { std::ofstream(path, std::ios::binary) << bytes; }

struct Child {
    PROCESS_INFORMATION process{};
    ~Child() {
        if (!process.hProcess) return;
        if (WaitForSingleObject(process.hProcess, 0) == WAIT_TIMEOUT) TerminateProcess(process.hProcess, 99);
        WaitForSingleObject(process.hProcess, 5000);
        CloseHandle(process.hProcess);
        CloseHandle(process.hThread);
    }
};

int wmain(int argc, wchar_t** argv)
{
    try {
        if (argc == 4) {
            const int fd = checkpoint::openTemporary(utf8(argv[2]), true);
            require(fd >= 0, "child creates temporary file");
            FILE* writer = _fdopen(_dup(fd), "w+b");
            require(writer && std::fputs("partial image", writer) >= 0 && std::fflush(writer) == 0,
                    "child writes through duplicate stream");
            HANDLE ready = OpenEventW(EVENT_MODIFY_STATE, FALSE, argv[3]);
            require(ready && SetEvent(ready), "child signals ready");
            CloseHandle(ready);
            Sleep(INFINITE);
        }
        const auto directory = fs::temp_directory_path() / (L"moonray checkpoint \u00e9 " + std::to_wstring(GetCurrentProcessId()));
        fs::create_directory(directory);
        const auto source = directory / L"temp\u00e9.exr";
        const auto staged = directory / "staged.exr";
        const auto second = directory / "second.exr";
        const auto output = directory / L"final\u00e9.exr";
        std::string payload(200000, '\0');
        for (size_t i = 0; i < payload.size(); ++i) payload[i] = static_cast<char>(i);
        write(source, payload);
        const int fd = checkpoint::openTemporary(utf8(source));
        require(fd >= 0, "open temporary");
        write(staged, std::string(payload.size() * 2, 'z'));
        std::string error;
        require(checkpoint::copyTemporary(fd, utf8(staged), error), "copy binary and truncate existing destination");
        require(read(staged) == payload, "exact binary data");
        auto concurrent = std::async(std::launch::async, [&] {
            std::string error;
            require(checkpoint::copyTemporary(fd, utf8(second), error), "parallel copy");
        });
        require(checkpoint::copyTemporary(fd, utf8(staged), error), "repeated copy starts at zero");
        concurrent.get();
        require(read(staged) == payload && read(second) == payload, "independent copy offsets");
        require(!checkpoint::copyTemporary(fd, utf8(directory / "missing" / "out.exr"), error) && !error.empty(), "copy errors reported");
        write(output, "old checkpoint");
        require(checkpoint::replace(utf8(staged), utf8(output), error), "replace previous checkpoint");
        require(read(output) == payload && !fs::exists(staged), "replace preserves new data");
        require(_close(fd) == 0 && !fs::exists(source), "close deletes temporary file");
        const int outputFd = checkpoint::openTemporary(utf8(source), true);
        require(outputFd >= 0, "create temporary writer");
        FILE* writer = _fdopen(_dup(outputFd), "w+b");
        require(writer != nullptr, "duplicate writer stream");
        require(std::fwrite(payload.data(), 1, payload.size(), writer) == payload.size(), "write binary through stream");
        require(std::fclose(writer) == 0, "close writer while retaining copy descriptor");
        require(checkpoint::copyTemporary(outputFd, utf8(staged), error), "copy after writer closes");
        require(read(staged) == payload, "retained temporary contains entire image");
        require(_close(outputFd) == 0 && !fs::exists(source), "delete after final descriptor closes");
        fs::remove(staged);
        write(source, payload);
        const auto eventName = L"Local\\MoonrayCheckpointTest" + std::to_wstring(GetCurrentProcessId());
        HANDLE ready = CreateEventW(nullptr, TRUE, FALSE, eventName.c_str());
        require(ready != nullptr, "create child event");
        {
            Child child;
            wchar_t exe[32768];
            require(GetModuleFileNameW(nullptr, exe, 32768) > 0, "executable path");
            std::wstring command = L"\"" + std::wstring(exe) + L"\" hold \"" + source.wstring() + L"\" " + eventName;
            STARTUPINFOW startup{};
            startup.cb = sizeof(startup);
            require(CreateProcessW(nullptr, command.data(), nullptr, nullptr, FALSE, CREATE_NO_WINDOW,
                nullptr, nullptr, &startup, &child.process), "start child");
            require(WaitForSingleObject(ready, 5000) == WAIT_OBJECT_0, "child opened file");
        } // Force termination with the file still open.
        CloseHandle(ready);
        require(!fs::exists(source), "process crash deletes temporary file");
        fs::remove(second);
        fs::remove(output);
        fs::remove(directory);
        std::cout << "Checkpoint files: writer streams, binary copy, repeat/parallel copies, replace, errors, crash cleanup passed\n";
        return 0;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
