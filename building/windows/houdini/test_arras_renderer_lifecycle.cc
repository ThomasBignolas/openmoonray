// SPDX-License-Identifier: Apache-2.0
// Uses the actual host delegate and an isolated local worker, without a UI.
#include <winsock2.h>
#include <windows.h>
#include <tlhelp32.h>
#include "ArrasRenderer.h"
#include <hydramoonray/RenderDelegate.h>
#include <scene_rdl2/scene/rdl2/Utils.h>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <thread>

using namespace hdMoonray;
using namespace pxr;
using namespace std::chrono_literals;

void require(bool ok, const char* reason)
{
    if (!ok) throw std::runtime_error(reason);
}

template<class Predicate> void waitFor(Predicate predicate, const char* reason)
{
    const auto deadline = std::chrono::steady_clock::now() + 15s;
    while (!predicate()) {
        require(std::chrono::steady_clock::now() < deadline, reason);
        std::this_thread::sleep_for(10ms);
    }
}

void stopOwnWorker()
{
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    require(snapshot != INVALID_HANDLE_VALUE, "process snapshot failed");
    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    DWORD worker = 0;
    unsigned count = 0;
    for (BOOL found = Process32FirstW(snapshot, &entry); found; found = Process32NextW(snapshot, &entry)) {
        if (entry.th32ParentProcessID == GetCurrentProcessId() && !_wcsicmp(entry.szExeFile, L"execComp.exe")) {
            worker = entry.th32ProcessID;
            ++count;
        }
    }
    CloseHandle(snapshot);
    require(count == 1, "expected exactly one worker belonging to this test");
    HANDLE process = OpenProcess(PROCESS_TERMINATE, FALSE, worker);
    require(process != nullptr, "could not open own worker");
    const bool stopped = TerminateProcess(process, 99) != FALSE;
    CloseHandle(process);
    require(stopped, "could not stop own worker");
}

std::vector<float> finishFrame(ArrasRenderer& renderer)
{
    renderer.endUpdate();
    waitFor([&] { return renderer.isFrameComplete() || renderer.getErrorStatus(); }, "frame timed out");
    require(!renderer.getErrorStatus(), "healthy frame reported an error");
    PixelData pixels;
    require(renderer.resolve(nullptr, pixels), "beauty could not be resolved");
    require(!pixels.vec.empty(), "empty beauty buffer");
    require(std::all_of(pixels.vec.begin(), pixels.vec.end(), [](float v) { return std::isfinite(v); }),
            "nonfinite beauty pixels");
    require(*std::max_element(pixels.vec.begin(), pixels.vec.end()) > .1f, "blank beauty buffer");
    return pixels.vec;
}

void run(const char* scene)
{
    auto* renderer = new ArrasRenderer;
    RenderDelegate delegate(renderer);
    delegate.SetRenderSetting(TfToken("moonray:localThreads"), VtValue(2));
    delegate.SetRenderSetting(TfToken("moonray:executionMode"), VtValue(std::string("vectorized")));
    RenderSettings settings(delegate);
    renderer->applySettings(settings);
    scene_rdl2::rdl2::readSceneFromFile(scene, renderer->getSceneContext());
    const auto reference = finishFrame(*renderer);
    std::cout << "initial frame passed\n" << std::flush;
    const auto restart = [&] {
        require(delegate.InvokeCommand(TfToken("restart_arras")), "restart command was rejected");
        require(!renderer->getErrorStatus(), "restart did not clear the error");
        require(!renderer->isFrameComplete(), "restart exposed a stale completed frame");
        const auto pixels = finishFrame(*renderer);
        require(pixels.size() == reference.size(), "restart changed image dimensions");
        float difference = 0;
        for (size_t i = 0; i < pixels.size(); ++i)
            difference = std::max(difference, std::abs(pixels[i] - reference[i]));
        require(difference < .01f, "restart changed image content");
    };
    restart();
    std::cout << "healthy restart passed\n" << std::flush;
    stopOwnWorker();
    waitFor([&] { return renderer->getErrorStatus() != 0; }, "worker loss was not reported");
    require(renderer->getStatusString().find("failed") != std::string::npos, "failure status is not visible");
    const auto stats = delegate.GetRenderStats();
    const auto error = stats.find("huskErrorStatus");
    require(error != stats.end() && error->second.Get<int>() != 0,
            "delegate did not expose the fatal error");
    renderer->beginUpdate();
    renderer->endUpdate();
    require(renderer->getErrorStatus() != 0, "ordinary update cleared a fatal error");
    restart();
    std::cout << "recovery after worker loss passed\n" << std::flush;
    // Destruction must safely join callbacks even with a newly queued frame.
    renderer->forceUpdate();
    renderer->endUpdate();
}

int main(int argc, char** argv)
{
    if (argc != 2) return 2;
    WSADATA data{};
    if (WSAStartup(MAKEWORD(2, 2), &data)) return 2;
    int result = 0;
    try { run(argv[1]); std::cout << "renderer lifecycle passed\n"; }
    catch (const std::exception& e) { std::cerr << e.what() << '\n'; result = 1; }
    WSACleanup();
    return result;
}
