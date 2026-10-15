# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param(
    [ValidateSet('Release', 'Debug', 'RelWithDebInfo')]
    [string]$Configuration = 'Release',
    [string[]]$Targets = @(),
    [int]$Jobs = 8,
    [switch]$ConfigureOnly
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Enter-BuildEnvironment.ps1"
$repo = (Resolve-Path "$PSScriptRoot/../..").Path.Replace('\', '/')
$deps = "$repo/build/deps/x64-windows"
$build = "$repo/build/windows/scene_rdl2-$Configuration"
$runtime = if ($Configuration -eq 'Debug') { "$deps/debug/bin" } else { "$deps/bin" }
$env:PATH = "$runtime;$repo/build/tools/tbb/bin/intel64/vc14;$env:PATH"
$env:CMAKE_MODULES_ROOT = "$repo/cmake_modules"
# Windows PowerShell represents redirected native stderr as error records.
# CMake warnings must not abort the script; check the native exit codes below.
$ErrorActionPreference = 'Continue'
& cmake -S "$repo/moonray/scene_rdl2" -B $build -G Ninja `
    "-DCMAKE_BUILD_TYPE=$Configuration" `
    "-DCMAKE_MODULE_PATH=$repo/cmake_modules/cmake" `
    "-DCMAKE_TOOLCHAIN_FILE=$repo/build/tools/vcpkg/scripts/buildsystems/vcpkg.cmake" `
    "-DVCPKG_INSTALLED_DIR=$repo/build/deps" -DVCPKG_MANIFEST_MODE=OFF `
    "-DCMAKE_ISPC_COMPILER=$repo/build/tools/ispc-v1.21.0-windows/bin/ispc.exe" `
    "-DTBB_ROOT=$repo/build/tools/tbb" `
    "-DCMAKE_INSTALL_PREFIX=$repo/build/install" `
    "-DPython_ROOT_DIR=$deps/tools/python3" `
    "-DLUA_BIN_LUA=$deps/tools/lua/lua.exe" `
    "-DLUA_BIN_LUAC=$deps/tools/lua/luac.exe" `
    -DBUILD_TESTING=ON
if ($LASTEXITCODE -ne 0) { throw 'scene_rdl2 configuration failed.' }
if (-not $ConfigureOnly) {
    $buildArgs = @('--build', $build, '--parallel', $Jobs)
    if ($Targets.Count) { $buildArgs += @('--target') + $Targets }
    & cmake @buildArgs
    if ($LASTEXITCODE -ne 0) { throw 'scene_rdl2 build failed.' }
}
