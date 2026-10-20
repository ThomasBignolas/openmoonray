// SPDX-License-Identifier: Apache-2.0
#include <mcrt_denoise/denoiser/Denoiser.h>
#include <scene_rdl2/render/logging/logging.h>
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>

int main()
{
    using namespace moonray::denoiser;
    scene_rdl2::logging::Logger::init();
    // Exercise destruction of partially constructed implementations through
    // the public API.
    for (const auto dims : {std::pair<int,int>{0, 32}, {-1, 32}, {32, 0},
                           {std::numeric_limits<int>::max(), std::numeric_limits<int>::max()}}) {
        std::string error;
        Denoiser failed(OPEN_IMAGE_DENOISE_CPU, dims.first, dims.second, true, true, &error);
        if (error.empty()) throw std::runtime_error("Invalid dimensions were accepted");
    }
    std::string error;
    Denoiser denoiser(OPEN_IMAGE_DENOISE_CPU, 16, 16, true, true, &error);
    if (!error.empty()) throw std::runtime_error(error);
    std::vector<float> beauty(16 * 16 * 4, .25f), albedo(beauty.size(), .5f),
        normal(beauty.size(), 0.f), output(beauty.size(), -1.f);
    for (size_t i = 0; i < 256; ++i) {
        normal[i * 4 + 2] = 1.f;
        beauty[i * 4 + 3] = float(i) / 256.f;
    }
    denoiser.denoise(beauty.data(), nullptr, normal.data(), output.data(), &error);
    if (error.empty()) throw std::runtime_error("Missing guide was accepted");
    error.clear();
    denoiser.denoise(beauty.data(), albedo.data(), normal.data(), output.data(), &error);
    if (!error.empty()) throw std::runtime_error(error);
    for (size_t i = 0; i < output.size(); ++i)
        if (!std::isfinite(output[i]) || (i % 4 == 3 && output[i] != beauty[i]))
            throw std::runtime_error("Non-finite result or changed alpha");
    std::cout << "OIDN failure cleanup, recovery and alpha checks passed\n";
}
