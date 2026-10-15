#include <cstdint>

extern "C" const unsigned char windows_sampling_fixture_start[];
extern "C" const unsigned char windows_sampling_fixture_end[];

int main()
{
    const auto start = reinterpret_cast<uintptr_t>(windows_sampling_fixture_start);
    const auto end = reinterpret_cast<uintptr_t>(windows_sampling_fixture_end);
    if (end - start != 771 || start % 64 != 0) return 1;
    for (unsigned i = 0; i < 768; ++i) {
        if (windows_sampling_fixture_start[i] != i % 256) return 2;
    }
    return windows_sampling_fixture_start[768] != 0 ||
           windows_sampling_fixture_start[769] != 255 ||
           windows_sampling_fixture_start[770] != 26;
}
