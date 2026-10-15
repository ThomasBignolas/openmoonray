#include <common/mcrt_util/CPUID.h>
#include <common/mcrt_util/ProcessStats.h>
#include <rendering/mcrt_common/Clock.h>

#include <atomic>
#include <chrono>
#include <thread>
#include <iostream>
#include <stdexcept>

int main()
{
    moonray::util::CPUID cpu;
    moonray::util::ProcessStats process;
    if (cpu.vendor().empty() || !cpu.sse2() || !cpu.atomic_64() || !cpu.atomic_128()) {
        throw std::runtime_error("Native CPU feature query failed");
    }
    const auto initial = process.getProcessUtilization();
    const auto final = process.getProcessUtilization();
    if (initial.userTime < 0 || initial.systemTime < 0 || final.userTime < initial.userTime ||
        final.systemTime < initial.systemTime || process.getProcessMemory() <= 0 || process.getBytesRead() < 0) {
        throw std::runtime_error("Native process statistics query failed");
    }
    int64_t sleepingCpu = 0, workingCpu = 0;
    {
        moonray::mcrt_common::Clock clock(&sleepingCpu);
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    {
        moonray::mcrt_common::Clock clock(&workingCpu);
        const auto until = std::chrono::steady_clock::now() + std::chrono::milliseconds(200);
        while (std::chrono::steady_clock::now() < until) std::atomic_signal_fence(std::memory_order_seq_cst);
    }
    if (sleepingCpu >= 50000000 || workingCpu <= 0) {
        throw std::runtime_error("Renderer timer must measure thread CPU time, excluding sleep");
    }
    std::cout << cpu.vendor() << ": native CPU features, process statistics and thread CPU timing passed\n";
}
