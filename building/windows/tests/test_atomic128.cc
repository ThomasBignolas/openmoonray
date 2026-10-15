#include <scene_rdl2/render/util/Atomic128.h>
#include <atomic>
#include <thread>
#include <vector>

struct alignas(16) Value { std::uint64_t count, inverse; };

int main()
{
    using namespace scene_rdl2::util;
    Value shared{7, ~std::uint64_t(7)};
    Value expected{0, 0};
    Value desired{11, ~std::uint64_t(11)};
    if (atomicCmpxchg128(&shared, &expected, &desired)) return 1;
    if (expected.count != 7 || expected.inverse != ~std::uint64_t(7)) return 2;
    if (!atomicCmpxchg128(&shared, &expected, &desired)) return 3;
    Value read{};
    atomicLoad128(&shared, &read);
    if (read.count != 11 || read.inverse != ~std::uint64_t(11)) return 4;

    Value zero{0, ~std::uint64_t(0)};
    atomicStore128(&shared, &zero);
    std::atomic<bool> torn{false};
    std::vector<std::thread> threads;
    for (int t = 0; t != 4; ++t) {
        threads.emplace_back([&] {
            for (int i = 0; i != 25000; ++i) {
                Value old{};
                atomicLoad128(&shared, &old);
                for (;;) {
                    if (old.inverse != ~old.count) torn = true;
                    Value next{old.count + 1, ~(old.count + 1)};
                    if (atomicCmpxchg128(&shared, &old, &next)) break;
                }
            }
        });
    }
    for (auto& thread : threads) thread.join();
    atomicLoad128(&shared, &read);
    if (torn || read.count != 100000 || read.inverse != ~read.count) return 5;
    return 0;
}
