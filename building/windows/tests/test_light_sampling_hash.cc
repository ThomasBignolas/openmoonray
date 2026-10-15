// SPDX-License-Identifier: Apache-2.0

#include "light/LightSamplingHash.h"

#include <array>
#include <cstdio>

int main()
{
    // Captured from std::hash<std::string> in the Ubuntu x86-64 reference VM
    // (GCC 13 / libstdc++), independently of the Windows implementation.
    // High-bit bytes and every tail length exercise signed-char and width bugs.
    constexpr std::array<std::uint32_t, 33> expected = {{
        507914862u, 3352336491u, 474652110u, 4138273764u, 4070150025u,
        1220727984u, 1719022781u, 3205754927u, 2929516122u, 2375020469u,
        497520659u, 2551215973u, 1107193571u, 231656045u, 1801897261u,
        3029852088u, 3197500033u, 3466526129u, 4227839943u, 1363040151u,
        4173378084u, 1298913696u, 3854971848u, 1904417481u, 330416407u,
        2645141669u, 635192937u, 3804028229u, 1189454009u, 1635965090u,
        1921284797u, 3112031289u, 2473524864u
    }};
    for (std::size_t length = 0; length < expected.size(); ++length) {
        std::string name;
        for (std::size_t i = 0; i < length; ++i) name.push_back(static_cast<char>(i * 37 + 129));
        if (moonray::pbr::lightSamplingHash(name) != expected[length]) {
            std::fprintf(stderr, "Light sampling hash differs from Linux at length %zu\n", length);
            return 1;
        }
    }
    if (moonray::pbr::lightSamplingHash("/Scene/lighting/env") != 4199703079u ||
        moonray::pbr::lightSamplingHash(std::string("a\0b", 3)) != 2709990447u ||
        moonray::pbr::lightSamplingHash(std::string(256, '\xff')) != 1139596371u) {
        std::fputs("Named, embedded-NUL or long light sampling hash differs from Linux\n", stderr);
        return 1;
    }
    std::puts("PASS: 36 independent Linux light-sampling hash fixtures");
    return 0;
}
