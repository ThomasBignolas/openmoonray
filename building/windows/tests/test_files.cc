#include <scene_rdl2/render/util/Files.h>
#include <filesystem>
#include <fstream>
#include <iostream>

int main(int argc, char** argv)
{
    if (argc != 2) return 1;
    namespace fs = std::filesystem;
    using namespace scene_rdl2::util;
    try {
        const auto root = fs::absolute(argv[1]);
        fs::create_directories(root);
        const auto original = root / "original.txt";
        { std::ofstream file(original); file << "preserve this content"; }
        if (!fileExists(original.string()) || fileExists((root / "missing").string())) return 2;
        if (!writeTest(original.string(), false)) return 3;
        std::string text;
        { std::ifstream file(original); std::getline(file, text); }
        if (text != "preserve this content") return 4;
        const auto probe = root / "created" / "child" / "probe.txt";
        if (!writeTest(probe.string(), true) || fs::exists(probe)) return 5;
        if (!createDirectories((root / "another" / "child" / "output.exr").string())) return 6;
        if (!fs::is_directory(root / "another" / "child")) return 7;
        const auto found = findFile("original.txt", (root / "missing").string() + ";" + root.string());
        if (found.empty() || !fs::equivalent(fs::path(found), original)) return 8;
        if (!isAbsolute(root.string()) || isAbsolute("C:relative.txt") || !isAbsolute("\\\\server\\share\\file")) return 9;
        if (!fs::equivalent(absolutePath("original.txt", root.string()), original)) return 10;
        if (simplifyPath("C:\\one\\two\\..\\three") != "C:/one/three") return 11;
        const auto copy = root / "copy.txt";
        copyFile(original.string(), copy.string());
        if (fs::file_size(original) != fs::file_size(copy)) return 12;
        if (!fs::equivalent(currentWorkingDirectory(), fs::current_path())) return 13;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 14;
    }
    return 0;
}
