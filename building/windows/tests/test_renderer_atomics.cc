#include <common/mcrt_util/Atomic.h>

#include <array>
#include <bit>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <thread>

using namespace moonray::util;

static void require(bool condition)
{
    if (!condition) {
        std::cerr << "Renderer atomic invariant failed\n";
        std::abort();
    }
}

int main()
{
    alignas(4) float value = -0.0f;
    float expected = 0.0f;
    require(!atomicCompareAndSwapStrong(&value, expected, 1.0f));
    require(std::bit_cast<uint32_t>(expected) == 0x80000000u);
    require(atomicCompareAndSwapWeak(&value, expected, 1.0f, std::memory_order_acq_rel));
    atomicAssignFloat(&value, 2.0f, std::memory_order_release);
    require(atomicLoad(&value, std::memory_order_acquire) == 2.0f);

    const float nan = std::bit_cast<float>(0x7fc00042u);
    atomicStore(&value, nan);
    expected = nan;
    require(atomicCompareAndSwapStrong(&value, expected, 0.0f));

    struct Pair { uint64_t count, inverse; };
    alignas(16) Pair pair{0, ~uint64_t{0}};
    Pair wrong{1, 2};
    require(!atomicCompareAndSwapStrong(&pair, wrong, Pair{3, 4}));
    require(wrong.count == 0 && wrong.inverse == ~uint64_t{0});
    atomicStore(&pair, Pair{0, ~uint64_t{0}});

    alignas(4) float minimum = std::numeric_limits<float>::infinity();
    alignas(4) float maximum = -std::numeric_limits<float>::infinity();
    alignas(16) float closest[4] = {0, 0, 0, std::numeric_limits<float>::infinity()};
    constexpr unsigned iterations = 10000;
    std::array<std::thread, 4> workers;
    for (unsigned worker = 0; worker != workers.size(); ++worker) {
        workers[worker] = std::thread([&, worker] {
            for (unsigned i = 0; i != iterations; ++i) {
                const float candidate = static_cast<float>(worker * iterations + i + 1);
                atomicAdd(&value, 1.0f);
                atomicMin(&minimum, candidate);
                atomicMax(&maximum, candidate);
                alignas(16) float sample[4] = {candidate, -candidate, candidate * 2, candidate};
                atomicAssignIfClosest(closest, sample);
                alignas(16) float snapshot[4];
                atomicLoadFloat4(snapshot, closest);
                require(snapshot[0] == snapshot[3] && snapshot[1] == -snapshot[3] &&
                        snapshot[2] == snapshot[3] * 2);
                Pair previous = atomicLoad(&pair, std::memory_order_relaxed);
                do {
                    require(previous.inverse == ~previous.count);
                } while (!atomicCompareAndSwapWeak(&pair, previous,
                    Pair{previous.count + 1, ~(previous.count + 1)}, std::memory_order_relaxed));
            }
        });
    }
    for (auto& worker : workers) worker.join();
    require(atomicLoad(&value) == workers.size() * iterations);
    require(atomicLoad(&minimum) == 1 && atomicLoad(&maximum) == workers.size() * iterations);
    const Pair result = atomicLoad(&pair);
    require(result.count == workers.size() * iterations && result.inverse == ~result.count);
    require(closest[0] == 1 && closest[1] == -1 && closest[2] == 2 && closest[3] == 1);
}
