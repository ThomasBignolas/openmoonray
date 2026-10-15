# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param([int]$Jobs = 8, [switch]$ConfigureOnly)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Enter-BuildEnvironment.ps1"
$repo = (Resolve-Path "$PSScriptRoot/../..").Path.Replace('\', '/')
$build = "$repo/build/windows/arras"
$env:CMAKE_MODULES_ROOT = "$repo/cmake_modules"
$ErrorActionPreference = 'Continue'
& cmake -S "$PSScriptRoot/arras" -B $build -G Ninja `
    -DCMAKE_BUILD_TYPE=Release "-DCMAKE_INSTALL_PREFIX=$repo/build/deps-arras" `
    "-DCMAKE_TOOLCHAIN_FILE=$repo/build/tools/vcpkg/scripts/buildsystems/vcpkg.cmake" `
    "-DVCPKG_INSTALLED_DIR=$repo/build/deps" -DVCPKG_MANIFEST_MODE=OFF `
    -DBUILD_TESTING=ON
if ($LASTEXITCODE -ne 0) { throw 'Arras configuration failed.' }
if ($ConfigureOnly) { return }
& cmake --build $build --parallel $Jobs
if ($LASTEXITCODE -ne 0) { throw 'Arras build failed.' }
& cmake --install $build
if ($LASTEXITCODE -ne 0) { throw 'Arras installation failed.' }
