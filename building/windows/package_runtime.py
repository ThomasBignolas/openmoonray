"""Build a relocatable Windows CPU runtime from the pinned installations.

Run through Package-MoonRay.ps1, which selects the matching MSVC redistributables.
The output must be a new directory. Failed staging directories are retained.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def cmake_string(value, normalize=True):
    value = str(value).replace("\\", "/") if normalize else str(value)
    if ";" in value:
        raise ValueError("CMake runtime scanning cannot use paths containing semicolons")
    delimiter = "="
    while "]" + delimiter + "]" in value:
        delimiter += "="
    return "[" + delimiter + "[" + value + "]" + delimiter + "]"


def package(args):
    repo = Path(__file__).resolve().parents[2]
    install = args.install.resolve(strict=True)
    output = args.output.resolve()
    if output.exists():
        raise ValueError(f"Output already exists: {output}")
    # Packaging and the final relocation stay in the user-authorized workspace.
    if not output.is_relative_to(repo) or output == repo:
        raise ValueError("Choose a new output directory within the checkout")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="moonray-package-", dir=output.parent))
    print(f"Staging runtime in {staging}", flush=True)
    origins = {}

    def copy_file(source, relative):
        source = Path(source)
        if source.stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError(f"Do not package filesystem links: {source}")
        destination = staging / relative
        if destination.exists():
            if digest(source) != digest(destination):
                raise ValueError(f"Conflicting runtime files: {source} and {destination}")
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        origin = source.relative_to(repo).as_posix() if source.is_relative_to(repo) else f"MSVC-redist/{source.name}"
        origins[destination.relative_to(staging).as_posix()] = origin

    def copy_tree(source, relative):
        source = Path(source)
        if not source.is_dir():
            raise FileNotFoundError(source)
        for folder, dirs, files in os.walk(source, followlinks=False):
            dirs[:] = [name for name in dirs if name != "__pycache__"]
            for name in dirs:
                if (Path(folder) / name).stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise ValueError(f"Do not package directory links: {Path(folder) / name}")
            for name in files:
                if not name.endswith((".pyc", ".pyo", ".pdb", ".lib", ".exp")):
                    path = Path(folder) / name
                    copy_file(path, Path(relative) / path.relative_to(source))

    deps = repo / "build/deps/x64-windows"
    extra = repo / "build/deps-extra"
    arras = repo / "build/deps-arras"
    oidn = repo / "build/tools/oidn-2.3.3.x64.windows"
    python = deps / "tools/python3"
    crt = args.crt.resolve(strict=True)
    for required in (install / "bin/moonray.exe", install / "bin/hd_render.exe",
                     install / "bin/computation_progmcrt.dll", arras / "bin/execComp.exe"):
        if not required.is_file():
            raise FileNotFoundError(f"Build and install MoonRay with -WithArras first: {required}")
    crt_names = {path.name.lower() for path in crt.glob("*.dll")}
    for path in crt.glob("*.dll"):
        copy_file(path, Path("bin") / path.name)
    for folder in (install / "bin", arras / "bin"):
        for path in folder.iterdir():
            if path.suffix.lower() in (".exe", ".dll") and path.name.lower() not in crt_names:
                copy_file(path, Path("bin") / path.name)
    for name in ("coredata", "rdl2dso", "plugin", "sessions"):
        copy_tree(install / name, name)
    # Preserve USD's relative LibraryPath and ResourcePath entries.
    copy_tree(extra / "lib/usd", "lib/usd")
    copy_tree(extra / "plugin/usd", "plugin/usd")
    for path in (extra / "lib").glob("*.dll"):
        copy_file(path, Path("lib") / path.name)
    for name in ("usdcat.exe", "usdtree.exe", "sdfdump.exe", "sdffilter.exe"):
        copy_file(extra / "bin" / name, Path("bin") / name)
    for name in ("oiiotool.exe", "idiff.exe", "maketx.exe", "iinfo.exe"):
        copy_file(deps / "tools/openimageio" / name, Path("bin") / name)
    # OIDN loads its device backend dynamically. This package uses the CPU backend.
    for name in ("OpenImageDenoise.dll", "OpenImageDenoise_core.dll", "OpenImageDenoise_device_cpu.dll"):
        copy_file(oidn / "bin" / name, Path("bin") / name)
    copy_tree(python, "python")
    copy_tree(extra / "lib/python", "python/Lib/site-packages")
    copy_tree(install / "python/lib/python3.11", "python/Lib/site-packages")
    copy_tree(deps / "lib/python3.11/site-packages/OpenImageIO", "python/Lib/site-packages/OpenImageIO")
    # These upstream modules provide the SDR plugin's Python registration names.
    for module in ("Discovery", "Parser"):
        source = repo / f"moonray/hydra/moonray_sdr_plugins/moonrayShader{module}/__init__.py"
        copy_file(source, f"python/Lib/site-packages/pxr/MoonrayShader{module}/__init__.py")
    for name in ("Setup.ps1", "Setup.cmd"):
        copy_file(repo / "building/windows/runtime" / name, name)
    copy_file(repo / "building/windows/runtime/sitecustomize.py", "python/Lib/sitecustomize.py")

    search = [staging / "bin", staging / "lib", staging / "python", staging / "python/DLLs",
              deps / "bin", deps / "tools/openimageio", extra / "bin", extra / "lib", arras / "bin",
              repo / "build/tools/tbb/bin/intel64/vc14", oidn / "bin", crt]
    binaries = list(staging.rglob("*.exe"))
    libraries = list(staging.rglob("*.dll")) + list(staging.rglob("*.pyd"))
    windows_pattern = "".join(f"[{c.lower()}{c.upper()}]" if c.isalpha() else
                              r"[/\\]" if c == "/" else re.escape(c)
                              for c in Path(os.environ["SystemRoot"]).as_posix()) + r"[/\\].*"
    scan = ["cmake_minimum_required(VERSION 3.23)",
            "set(CMAKE_GET_RUNTIME_DEPENDENCIES_PLATFORM windows+pe)",
            "set(CMAKE_GET_RUNTIME_DEPENDENCIES_TOOL dumpbin)",
            f"set(CMAKE_GET_RUNTIME_DEPENDENCIES_COMMAND {cmake_string(args.dumpbin)})",
            "file(GET_RUNTIME_DEPENDENCIES RESOLVED_DEPENDENCIES_VAR resolved",
            "UNRESOLVED_DEPENDENCIES_VAR unresolved CONFLICTING_DEPENDENCIES_PREFIX conflicts",
            "EXECUTABLES " + " ".join(map(cmake_string, binaries)),
            "LIBRARIES " + " ".join(map(cmake_string, libraries)),
            "DIRECTORIES " + " ".join(map(cmake_string, search)),
            'PRE_EXCLUDE_REGEXES "^api-ms-" "^ext-ms-"',
            f"POST_EXCLUDE_REGEXES {cmake_string(windows_pattern, normalize=False)})",
            f'file(WRITE {cmake_string(staging / "runtime-dependencies.txt")} "${{resolved}}")',
            'if(unresolved)\n message(FATAL_ERROR "Unresolved DLLs: ${unresolved}")\nendif()',
            'foreach(name IN LISTS conflicts_FILENAMES)\n set(hashes)\n'
            ' foreach(path IN LISTS conflicts_${name})\n file(SHA256 "${path}" hash)\n'
            ' list(APPEND hashes "${hash}")\n endforeach()\n list(REMOVE_DUPLICATES hashes)\n'
            ' list(LENGTH hashes count)\n if(count GREATER 1)\n'
            ' message(FATAL_ERROR "Conflicting DLLs: ${conflicts_${name}}")\n endif()\nendforeach()']
    scan_file = staging / "scan-runtime.cmake"
    scan_file.write_text("\n".join(scan) + "\n")
    print(f"Scanning {len(binaries)} executables and {len(libraries)} DLLs/extensions", flush=True)
    with (staging / "dependency-scan.log").open("w") as log:
        subprocess.run([args.cmake, "-P", str(scan_file)], stdout=log, stderr=subprocess.STDOUT, check=True)
    resolved = (staging / "runtime-dependencies.txt").read_text().split(";")
    for item in filter(None, resolved):
        path = Path(item).resolve()
        if not path.is_relative_to(staging):
            copy_file(path, Path("bin") / path.name)
    for name in ("runtime-dependencies.txt", "scan-runtime.cmake", "dependency-scan.log"):
        (staging / name).unlink()

    # Retain copyright/license texts from every pinned dependency distribution.
    for source in (deps / "share").glob("*/copyright"):
        copy_file(source, Path("licenses/vcpkg") / source.parent.name / "copyright")
    notices = [(repo / "LICENSE", "openmoonray/LICENSE"),
               (repo / "build/tools/tbb/LICENSE", "tbb/LICENSE"),
               (extra / "share/doc/embree4/LICENSE.txt", "embree/LICENSE.txt"),
               (repo / "build/dependency-sources/openvdb-10.0.1/LICENSE", "openvdb/LICENSE"),
               (repo / "build/dependency-sources/usd-23.08/LICENSE.txt", "usd/LICENSE.txt"),
               (repo / "build/dependency-sources/usd-23.08/NOTICE.txt", "usd/NOTICE.txt")]
    for submodule in ("arras/arras4_core", "moonray/scene_rdl2", "moonray/moonray", "moonray/moonshine",
                      "moonray/moonshine_usd", "moonray/mcrt_denoise", "moonray/hydra/hdMoonray",
                      "moonray/hydra/moonray_sdr_plugins", "moonray/moonray_arras/mcrt_messages",
                      "moonray/moonray_arras/mcrt_dataio", "moonray/moonray_arras/mcrt_computation"):
        notices.append((repo / submodule / "LICENSE", submodule + "/LICENSE"))
    notices.extend((path, "oidn/" + path.name) for path in (oidn / "doc").glob("*.txt"))
    for source, target in notices:
        copy_file(source, Path("licenses") / target)
    (staging / "README.txt").write_text(
        "OpenMoonRay Windows x64 CPU runtime\n\n"
        "Requires an AVX2-capable x64 CPU and Windows with AF_UNIX support.\n"
        "In PowerShell, dot-source .\\Setup.ps1. In cmd.exe, call Setup.cmd.\n"
        "Then use moonray, hd_render -renderer Moonray, hd_usd2rdl, or python.\n"
        "The Moonray Hydra backend launches a local Arras worker automatically.\n"
        "USD, Python 3.11, native Arras, CPU OIDN and MSVC runtime DLLs are included.\n"
        "This runtime does not include development headers, GPU backends, or DCC applications.\n"
        "Remote Arras services and trusted-reference image parity remain unverified.\n"
        "See licenses/ for bundled component notices and manifest.json for file hashes.\n")
    manifest = {"format": 1, "platform": "windows-x64", "renderer": "cpu-avx2",
                "files": [{"path": path.relative_to(staging).as_posix(), "sha256": digest(path),
                           "source": origins.get(path.relative_to(staging).as_posix(), "generated")}
                          for path in sorted(staging.rglob("*")) if path.is_file()]}
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # Both resolved paths are checked before moving this directory tree.
    if not staging.resolve().is_relative_to(repo) or not output.resolve().is_relative_to(repo):
        raise ValueError("Package relocation escaped the workspace")
    staging.rename(output)
    print(f"Packaged {len(manifest['files'])} files in {output}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--crt", required=True, type=Path)
    parser.add_argument("--cmake", required=True)
    parser.add_argument("--dumpbin", required=True)
    package(parser.parse_args())
