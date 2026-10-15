#include <common/platform/DynamicLibrary.h>
#include <iostream>

int main(int argc, char** argv)
{
    if (argc != 2) return 1;
    using scene_rdl2::util::DynamicLibrary;
    using Function = int (*)();
    try {
        // Opening a second reference and releasing it must not unload the first.
        DynamicLibrary first(argv[1]);
        {
            DynamicLibrary second(argv[1]);
            if (reinterpret_cast<Function>(second.symbol("fixture_value"))() != 42) return 2;
        }
        if (reinterpret_cast<Function>(first.symbol("fixture_value"))() != 42) return 3;
        bool missingSymbol = false;
        try { first.symbol("symbol_that_does_not_exist"); }
        catch (const std::exception& error) { missingSymbol = !std::string(error.what()).empty(); }
        if (!missingSymbol) return 4;
        // A failed symbol lookup must not poison subsequent lookups.
        if (reinterpret_cast<Function>(first.symbol("fixture_value"))() != 42) return 5;
        bool missingLibrary = false;
        try { DynamicLibrary missing(std::string(argv[1]) + ".does-not-exist"); }
        catch (const std::exception& error) { missingLibrary = !std::string(error.what()).empty(); }
        if (!missingLibrary) return 6;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 7;
    }
    return 0;
}
