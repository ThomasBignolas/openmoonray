# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param([int]$Jobs = 4, [switch]$ConfigureOnly)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Enter-BuildEnvironment.ps1"
$repo = (Resolve-Path "$PSScriptRoot/../..").Path.Replace('\', '/')
$build = "$repo/build/windows/arras-node"
$jobsToUse = [Math]::Max(1, [Math]::Min($Jobs, [Environment]::ProcessorCount - 1))
$env:CMAKE_MODULES_ROOT = "$repo/cmake_modules"
$ErrorActionPreference = 'Continue'
& cmake -S "$PSScriptRoot/arras" -B $build -G Ninja `
    -DCMAKE_BUILD_TYPE=Release "-DCMAKE_INSTALL_PREFIX=$repo/build/windows/arras-node-install" `
    "-DCMAKE_TOOLCHAIN_FILE=$repo/build/tools/vcpkg/scripts/buildsystems/vcpkg.cmake" `
    "-DVCPKG_INSTALLED_DIR=$repo/build/deps" -DVCPKG_MANIFEST_MODE=OFF `
    -DOMR_BUILD_ARRAS_NODE=ON -DARRASCORE_BUILD_TESTING=OFF -DBUILD_TESTING=ON
if ($LASTEXITCODE -ne 0) { throw 'Arras Node configuration failed.' }
if ($ConfigureOnly) { return }
& cmake --build $build --parallel $jobsToUse --target arras4_node arras4_router execComp
if ($LASTEXITCODE -ne 0) { throw 'Arras Node build failed.' }
