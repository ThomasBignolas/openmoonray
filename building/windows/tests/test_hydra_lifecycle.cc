// SPDX-License-Identifier: Apache-2.0
#include <pxr/imaging/hd/rendererPlugin.h>
#include <pxr/imaging/hd/rendererPluginRegistry.h>
#include <pxr/imaging/hd/renderDelegate.h>

#include <iostream>
#include <stdexcept>

int main(int argc, char** argv)
{
    auto& registry = pxr::HdRendererPluginRegistry::GetInstance();
    auto* plugin = registry.GetRendererPlugin(pxr::TfToken(
        argc > 1 ? argv[1] : "HdMoonrayRendererDebugPlugin"));
    if (!plugin) {
        std::cerr << "Native MoonRay Hydra plugin did not load\n";
        return 1;
    }
    pxr::HdRenderSettingsMap settings;
    settings[pxr::TfToken("threads")] = 2;
    // Recreate the global driver after releasing the last delegate, and ensure
    // deleting one of two live delegates does not destroy the other's driver.
    for (int iteration = 0; iteration < 2; ++iteration) {
        auto* first = plugin->CreateRenderDelegate(settings);
        auto* second = plugin->CreateRenderDelegate(settings);
        if (!first || !second) throw std::runtime_error("Delegate creation failed");
        plugin->DeleteRenderDelegate(first);
        plugin->DeleteRenderDelegate(second);
    }
    registry.ReleasePlugin(plugin);
    std::cout << "Repeated and overlapping Hydra delegate lifetimes passed\n";
    return 0;
}
