# SPDX-License-Identifier: Apache-2.0
"""Apply the Windows export and UTF-8 environment fixes for pinned USD 23.08."""

from pathlib import Path
import sys


header = Path(sys.argv[1]) / "pxr/usdImaging/usdImaging/lightAdapter.h"
original = "protected:\n    void _RemovePrim(SdfPath const& cachePath,"
replacement = "protected:\n    USDIMAGING_API\n    void _RemovePrim(SdfPath const& cachePath,"
text = header.read_text(encoding="utf-8")
if replacement not in text:
    if text.count(original) != 1:
        raise SystemExit(f"Unexpected USD light adapter header: {header}")
    # Its inline constructor emits a vtable in external subclasses. All the
    # referenced virtual functions must be exported from usdImaging.dll.
    header.write_text(text.replace(original, replacement), encoding="utf-8")

# USD's filesystem APIs use UTF-8, but 23.08 reads environment variables via
# GetEnvironmentVariableA. A relocated plugin path then becomes ANSI bytes.
env_source = Path(sys.argv[1]) / "pxr/base/arch/env.cpp"
text = env_source.read_text(encoding="utf-8")
if "// OpenMoonRay: preserve UTF-8 environment paths on Windows." not in text:
    substitutions = {
        '#include "pxr/base/arch/error.h"':
            '#include "pxr/base/arch/error.h"\n#include "pxr/base/arch/fileSystem.h"\n'
            '// OpenMoonRay: preserve UTF-8 environment paths on Windows.',
        '    const DWORD size = GetEnvironmentVariable(name.c_str(), nullptr, 0);\n'
        '    return size != 0 && size != ERROR_ENVVAR_NOT_FOUND;':
            '    SetLastError(ERROR_SUCCESS);\n'
            '    const DWORD size = GetEnvironmentVariableW(ArchWindowsUtf8ToUtf16(name).c_str(), nullptr, 0);\n'
            '    return size != 0 || GetLastError() != ERROR_ENVVAR_NOT_FOUND;',
        '    const DWORD size = GetEnvironmentVariable(name.c_str(), nullptr, 0);\n'
        '    if (size != 0) {\n'
        '        std::unique_ptr<char[]> buffer(new char[size]);\n'
        '        GetEnvironmentVariable(name.c_str(), buffer.get(), size);\n'
        '        return std::string(buffer.get());\n'
        '    }':
            '    const std::wstring wideName = ArchWindowsUtf8ToUtf16(name);\n'
            '    DWORD size = GetEnvironmentVariableW(wideName.c_str(), nullptr, 0);\n'
            '    while (size != 0) {\n'
            '        std::unique_ptr<wchar_t[]> buffer(new wchar_t[size]);\n'
            '        const DWORD count = GetEnvironmentVariableW(wideName.c_str(), buffer.get(), size);\n'
            '        if (count == 0) return std::string();\n'
            '        if (count < size) return ArchWindowsUtf16ToUtf8(buffer.get());\n'
            '        size = count;\n'
            '    }',
        '    if (!overwrite) {\n'
        '        const DWORD size = GetEnvironmentVariable(name.c_str(), nullptr, 0);\n'
        '        if (size == 0 || size != ERROR_ENVVAR_NOT_FOUND) {\n'
        '            // Already exists or error.\n'
        '            return true;\n'
        '        }\n'
        '    }\n'
        '    return SetEnvironmentVariable(name.c_str(), value.c_str()) != 0;':
            '    if (!overwrite && ArchHasEnv(name)) return true;\n'
            '    return SetEnvironmentVariableW(ArchWindowsUtf8ToUtf16(name).c_str(),\n'
            '                                   ArchWindowsUtf8ToUtf16(value).c_str()) != 0;',
        '    return SetEnvironmentVariable(name.c_str(), nullptr) != 0;':
            '    return SetEnvironmentVariableW(ArchWindowsUtf8ToUtf16(name).c_str(), nullptr) != 0;',
    }
    for original, replacement in substitutions.items():
        if text.count(original) != 1:
            raise SystemExit(f"Unexpected USD Windows environment source: {env_source}")
        text = text.replace(original, replacement)
    env_source.write_text(text, encoding="utf-8")


def replace_once(relative, original, replacement):
    path = Path(sys.argv[1]) / relative
    source = path.read_text(encoding="utf-8")
    if replacement in source:
        return
    if source.count(original) != 1:
        raise SystemExit(f"Unexpected USD source for UTF-8 patch: {path}")
    path.write_text(source.replace(original, replacement), encoding="utf-8")


replace_once("pxr/base/arch/library.cpp", '#include "pxr/base/arch/errno.h"',
             '#include "pxr/base/arch/errno.h"\n#include "pxr/base/arch/fileSystem.h"')
replace_once("pxr/base/arch/library.cpp", 'LoadLibrary(filename.c_str())',
             'LoadLibraryW(ArchWindowsUtf8ToUtf16(filename).c_str())')
replace_once("pxr/base/plug/info.cpp", '#include "pxr/base/plug/info.h"',
             '#include "pxr/base/plug/info.h"\n#include "pxr/base/arch/fileSystem.h"')
replace_once("pxr/base/plug/info.cpp", '    ifs.open(pathname.c_str());',
             '#if defined(ARCH_OS_WINDOWS)\n'
             '    ifs.open(ArchWindowsUtf8ToUtf16(pathname).c_str());\n'
             '#else\n    ifs.open(pathname.c_str());\n#endif')
replace_once("pxr/base/arch/symbols.cpp",
             '        char modName[MAX_PATH] = {0};\n'
             '        if (GetModuleFileName(module, modName, MAX_PATH)) {\n'
             '            objectPath->assign(modName);\n'
             '        }',
             '        std::wstring modName(32768, L\'\\0\');\n'
             '        const DWORD size = GetModuleFileNameW(module, &modName[0], static_cast<DWORD>(modName.size()));\n'
             '        if (!size || size >= modName.size()) return false;\n'
             '        modName.resize(size);\n'
             '        *objectPath = ArchWindowsUtf16ToUtf8(modName);')
replace_once("pxr/base/arch/systemInfo.cpp",
             '    // On Windows GetModuleFileName() returns the executable path.\n'
             '    return\n'
             '        _DynamicSizedRead(ARCH_PATH_MAX,\n'
             '            [](char* buffer, size_t* size) {\n'
             '                DWORD nSize = *size;\n'
             '                const DWORD n = GetModuleFileName(NULL, buffer, nSize);\n'
             '                if (n == 0) {\n'
             '                    ARCH_WARNING("Unable to read GetModuleFileName() to obtain "\n'
             '                                 "executable path");\n'
             '                    *size = std::numeric_limits<size_t>::max();\n'
             '                    return false;\n'
             '                }\n'
             '                else if (n >= nSize) {\n'
             '                    // We have to iterate to find a suitable size.\n'
             '                    *size *= 2;\n'
             '                    return false;\n'
             '                }\n'
             '                else {\n'
             '                    return true;\n'
             '                }\n'
             '            });',
             '    // Preserve the executable path as UTF-8, including long paths.\n'
             '    std::wstring buffer(32768, L\'\\0\');\n'
             '    const DWORD size = GetModuleFileNameW(NULL, &buffer[0], static_cast<DWORD>(buffer.size()));\n'
             '    if (!size || size >= buffer.size()) {\n'
             '        ARCH_WARNING("Unable to obtain executable path");\n'
             '        return std::string();\n'
             '    }\n'
             '    buffer.resize(size);\n'
             '    return ArchWindowsUtf16ToUtf8(buffer);')
