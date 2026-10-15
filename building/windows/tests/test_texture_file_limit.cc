// SPDX-License-Identifier: Apache-2.0
#include <moonray/rendering/texturing/sampler/TextureSampler.h>
#include <OpenImageIO/imageio.h>
#include <array>
#include <cstdio>
#include <filesystem>
#include <iostream>
#include <regex>
#include <stdexcept>

int main(int argc, char** argv)
{
    try {
        if (argc != 2) throw std::runtime_error("Pass a fixture output directory");
        const auto directory = std::filesystem::absolute(argv[1]);
        std::filesystem::create_directories(directory);
        // Reproduce the default CRT state of a fresh Windows worker.
        if (_setmaxstdio(512) == -1) throw std::runtime_error("Could not set baseline stream limit");
        moonray::texture::TextureSampler sampler;
        sampler.setOpenFileLimit(1024);
        auto* textures = sampler.getTextureSystem();
        textures->attribute("accept_unmipped", 1); // Tiny single-level fixture only.
        textures->attribute("deduplicate", 0);
        for (int i = 0; i < 700; ++i) {
            const auto path = (directory / (std::to_string(i) + ".exr")).string();
            OIIO::ImageSpec spec(8, 8, 1, OIIO::TypeFloat);
            spec.tile_width = spec.tile_height = 8;
            std::array<float, 64> pixels;
            pixels.fill(float(i) / 700.f);
            auto output = OIIO::ImageOutput::create(path);
            if (!output || !output->open(path, spec) ||
                    !output->write_image(OIIO::TypeFloat, pixels.data()) || !output->close()) {
                throw std::runtime_error("Could not write fixture " + path);
            }
            std::string error;
            auto* handle = sampler.getHandle(path, error);
            int channels = 0;
            if (!handle || !sampler.getTextureInfo(handle, "channels", &channels) || channels != 1) {
                throw std::runtime_error("Texture metadata failed at " + std::to_string(i) + ": " + error);
            }
        }
        const auto stats = textures->getstats(1);
        std::smatch match;
        const std::regex counts("ImageInputs\\s*:\\s*([0-9]+) created,\\s*([0-9]+) current");
        if (!std::regex_search(stats, match, counts)) throw std::runtime_error("Missing OIIO file counters");
        const int open = std::stoi(match[2]);
        int configured = 0;
        textures->getattribute("max_open_files", configured);
        std::cout << "CRT streams: " << _getmaxstdio() << "; OIIO limit: " << configured
                  << "; simultaneously open EXRs: " << open << '\n';
        if (open < 700 || configured < 700) throw std::runtime_error("Texture cache still hits the CRT stream ceiling");
        std::cout << "700 texture headers remained open without failed reads or forced eviction\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
