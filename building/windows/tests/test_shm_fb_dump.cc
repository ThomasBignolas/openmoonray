// SPDX-License-Identifier: Apache-2.0
#include <scene_rdl2/common/grid_util/ShmFb.h>

#include <windows.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
using namespace scene_rdl2::grid_util;

void require(bool ok, const char* message)
{
    if (!ok) throw std::runtime_error(message);
}

struct RemoveSegment {
    ShmDataManager& segment;
    ~RemoveSegment() { segment.rmShm(); }
};

void dump(const std::wstring& executable, int controlId, const std::filesystem::path& output)
{
    std::wstring command = L"\"" + executable + L"\" " + std::to_wstring(controlId) +
                           L" \"" + output.wstring() + L"\"";
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    require(CreateProcessW(executable.c_str(), command.data(), nullptr, nullptr, FALSE,
                           CREATE_NO_WINDOW, nullptr, nullptr, &startup, &process),
            "start framebuffer dump process");
    const DWORD wait = WaitForSingleObject(process.hProcess, 10000);
    if (wait != WAIT_OBJECT_0) {
        TerminateProcess(process.hProcess, 99);
        WaitForSingleObject(process.hProcess, 5000);
    }
    DWORD code = 99;
    const bool gotCode = GetExitCodeProcess(process.hProcess, &code) != 0;
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    require(wait == WAIT_OBJECT_0 && gotCode && code == 0, "framebuffer dump completion");
}

void check(const std::wstring& executable, const std::filesystem::path& output,
           ShmFb::ChanMode mode, bool topToBottom)
{
    ShmFbManager framebuffer(2, 2, 3, mode, topToBottom);
    RemoveSegment removeFramebuffer{framebuffer};
    ShmFbCtrlManager control;
    RemoveSegment removeControl{control};
    control.getFbCtrl()->setCurrentShmId(framebuffer.getShmId());

    // Pixel coordinates start at the bottom left, independent of memory order.
    const float rows[2][6] = {{1, 0, 0, 0, 1, 0}, {0, 0, 1, 0.25f, 0.5f, 0.75f}};
    for (unsigned y = 0; y < 2; ++y) {
        void* row = framebuffer.getFb()->getFbDataScanlineStartAddr(y);
        for (unsigned c = 0; c < 6; ++c) {
            switch (mode) {
            case ShmFb::ChanMode::UC8:
                static_cast<unsigned char*>(row)[c] = rows[y][c] == 1.0f ? 255 :
                    static_cast<unsigned char>(rows[y][c] * 256.0f);
                break;
            case ShmFb::ChanMode::H16:
                static_cast<unsigned short*>(row)[c] = ShmFb::f32toh16(rows[y][c]);
                break;
            case ShmFb::ChanMode::F32:
                static_cast<float*>(row)[c] = rows[y][c];
                break;
            }
        }
    }

    dump(executable, control.getShmId(), output);
    std::ifstream ppm(output);
    std::string magic;
    unsigned width = 0, height = 0, maxValue = 0;
    require(bool(ppm >> magic >> width >> height >> maxValue), "read PPM header");
    require(magic == "P3" && width == 2 && height == 2 && maxValue == 255, "PPM header");
    const int uc8AndFloat[] = {0, 0, 255, 64, 128, 192, 255, 0, 0, 0, 255, 0};
    // The upstream dump command scales half floats by 255 and full floats by
    // 256. Preserve that existing conversion behavior when checking the port.
    const int half[] = {0, 0, 255, 63, 127, 191, 255, 0, 0, 0, 255, 0};
    const int* expected = mode == ShmFb::ChanMode::H16 ? half : uc8AndFloat;
    for (int i = 0; i < 12; ++i) {
        int pixel = -1;
        require(bool(ppm >> pixel) && pixel == expected[i], "PPM pixel value and row order");
    }
    ppm >> std::ws;
    require(ppm.eof(), "no extra PPM pixels");
    require(control.rmShm(), "remove test control segment");
    require(framebuffer.rmShm(), "remove test framebuffer segment");
}
} // namespace

int wmain(int argc, wchar_t** argv)
{
    try {
        require(argc == 3, "expected dump executable and output path");
        const std::filesystem::path output(argv[2]);
        for (auto mode : {ShmFb::ChanMode::UC8, ShmFb::ChanMode::H16, ShmFb::ChanMode::F32}) {
            for (bool topToBottom : {false, true}) check(argv[1], output, mode, topToBottom);
        }
        std::filesystem::remove(output);
        std::cout << "Six cross-process framebuffer format/orientation checks passed.\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
    } catch (const std::string& error) {
        std::cerr << error << '\n';
    }
    return 1;
}
