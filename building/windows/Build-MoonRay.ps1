# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param([string[]]$Targets = @(), [int]$Jobs = 8, [switch]$ConfigureOnly, [switch]$WithArras,
      [switch]$WithOptix, [string]$OptixRoot)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Enter-BuildEnvironment.ps1"
. "$PSScriptRoot/Enter-MoonRayEnvironment.ps1"
$repo = (Resolve-Path "$PSScriptRoot/../..").Path.Replace('\', '/')
$deps = "$repo/build/deps/x64-windows"
$build = "$repo/build/windows/native"
$env:PATH = "$deps/bin;$repo/build/tools/tbb/bin/intel64/vc14;$repo/build/deps-extra/bin;$env:PATH"
$env:CMAKE_MODULES_ROOT = "$repo/cmake_modules"
$ErrorActionPreference = 'Continue'
$arrasOptions = @()
if ($WithArras) { $arrasOptions += '-DHDMOONRAY_BUILD_ARRAS_PLUGIN=ON' }
$gpuOptions = @('-DMOONRAY_USE_OPTIX=OFF')
if ($WithOptix) {
    if (!$OptixRoot) { $OptixRoot = "$repo/build/tools/optix-9.1.0" }
    if (!(Test-Path -LiteralPath "$OptixRoot/include/optix.h")) {
        throw "OptiX headers missing: $OptixRoot/include/optix.h. See the Houdini README XPU build instructions."
    }
    $gpuOptions = @('-DMOONRAY_USE_OPTIX=ON', "-DOptiX_INCLUDE_DIRS=$OptixRoot/include")
    if ($env:CUDA_PATH) { $gpuOptions += "-DCUDAToolkit_ROOT=$env:CUDA_PATH" }
}
& cmake -S "$PSScriptRoot/native" -B $build -G Ninja `
    -DCMAKE_BUILD_TYPE=Release "-DCMAKE_INSTALL_PREFIX=$repo/build/install" `
    "-DCMAKE_TOOLCHAIN_FILE=$repo/build/tools/vcpkg/scripts/buildsystems/vcpkg.cmake" `
    "-DVCPKG_INSTALLED_DIR=$repo/build/deps" -DVCPKG_MANIFEST_MODE=OFF `
    "-DCMAKE_PREFIX_PATH=$repo/build/deps-extra;$repo/build/deps-arras;$repo/build/tools/oidn-2.3.3.x64.windows" `
    "-DCMAKE_ISPC_COMPILER=$repo/build/tools/ispc-v1.21.0-windows/bin/ispc.exe" `
    "-DTBB_ROOT=$repo/build/tools/tbb" "-DPython_ROOT_DIR=$deps/tools/python3" `
    -DBOOST_PYTHON_COMPONENT_NAME=python311 `
    "-DLUA_BIN_LUA=$deps/tools/lua/lua.exe" "-DLUA_BIN_LUAC=$deps/tools/lua/luac.exe" `
    "-DBISON_EXECUTABLE=$repo/build/tools/winflexbison/win_bison.exe" `
    "-DFLEX_EXECUTABLE=$repo/build/tools/winflexbison/win_flex.exe" `
    "-DIDIFF=$deps/tools/openimageio/idiff.exe" `
    "-DOIIOTOOL=$deps/tools/openimageio/oiiotool.exe" `
    -DMOONRAY_USE_METAL=OFF -DBUILD_QT_APPS=OFF `
    -DBUILD_TESTING=ON @arrasOptions @gpuOptions
if ($LASTEXITCODE -ne 0) { throw 'MoonRay configuration failed.' }
if ($ConfigureOnly) { return }
$buildArgs = @('--build', $build, '--parallel', $Jobs)
if ($Targets.Count) { $buildArgs += @('--target') + $Targets }
& cmake @buildArgs
if ($LASTEXITCODE -ne 0) { throw 'MoonRay build failed.' }
