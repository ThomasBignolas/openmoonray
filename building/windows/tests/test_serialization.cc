// SPDX-License-Identifier: Apache-2.0
#include <scene_rdl2/render/cache/ValueContainerUtils.h>
#include <scene_rdl2/scene/rdl2/ValueContainerUtil.h>

#include <array>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <iostream>
#include <limits>
#include <stdexcept>

template<class Codec, class T>
void check(T value, std::initializer_list<unsigned char> wire)
{
    std::array<unsigned char, 16> buffer{};
    const auto size = Codec::variableLengthEncoding(value, buffer.data());
    if (size != wire.size() || std::memcmp(buffer.data(), wire.begin(), size) ||
        Codec::variableLengthEncodingSize(value) != size) {
        throw std::runtime_error("Encoded bytes differ from the scene wire format");
    }
    T result{};
    if (Codec::variableLengthDecoding(buffer.data(), result) != size || result != value) {
        throw std::runtime_error("64-bit wire value failed to round-trip");
    }
}

template<class Codec>
void checkCodec()
{
    check<Codec>(uint64_t(0), {0});
    check<Codec>(uint64_t(127), {0x7f});
    check<Codec>(uint64_t(128), {0x80, 1});
    check<Codec>(uint64_t(1) << 32, {0x80, 0x80, 0x80, 0x80, 0x10});
    check<Codec>(uint64_t(1) << 63, {0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 1});
    check<Codec>(std::numeric_limits<uint64_t>::max(),
        {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 1});
    check<Codec>(int64_t(-1), {1});
    check<Codec>(int64_t(1), {2});
    check<Codec>(std::numeric_limits<int64_t>::max(),
        {0xfe, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 1});
    check<Codec>(std::numeric_limits<int64_t>::min(),
        {0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 1});
    check<Codec>(std::numeric_limits<int32_t>::min(), {0xff, 0xff, 0xff, 0xff, 0x0f});
}

int main()
{
    try {
        checkCodec<scene_rdl2::cache::ValueContainerUtil>();
        checkCodec<scene_rdl2::rdl2::ValueContainerUtil>();
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
