# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param([string]$HoudiniRoot = 'C:/Houdini21', [int]$Jobs = 6)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Enter-BuildEnvironment.ps1"
$repo = (Resolve-Path "$PSScriptRoot/../..").Path.Replace('\', '/')
$build = "$repo/build/windows/houdini/native"
$install = "$repo/build/windows/houdini/install"
$runtime = Get-Content "$repo/build/windows/current-runtime-archive.json" -Raw | ConvertFrom-Json
$worker = "$repo/build/windows/houdini/worker-deep"
$workerOptions = @()
if (Select-String -LiteralPath "$repo/build/windows/native/CMakeCache.txt" -Pattern '^MOONRAY_USE_OPTIX:BOOL=ON$' -Quiet) {
    $worker = "$repo/build/windows/houdini/worker-xpu"
    $workerOptions += '--xpu'
}
$ErrorActionPreference = 'Continue' # Native tools write ordinary warnings to stderr; check their exit codes below.
. "$PSScriptRoot/Enter-MoonRayEnvironment.ps1"
& cmake --build "$repo/build/windows/native" --target grid_engine_tool computation_engine_mcrt ImageMap UsdUVTexture denoise --parallel $Jobs
if ($LASTEXITCODE -ne 0) { throw 'Houdini worker build failed.' }
& "$repo/build/deps/x64-windows/tools/python3/python.exe" "$PSScriptRoot/houdini/stage_worker.py" `
    --base $runtime.bundle --destination $worker @workerOptions
if ($LASTEXITCODE -ne 0) { throw 'Houdini worker staging failed.' }
& cmake -S "$PSScriptRoot/houdini" -B $build -G Ninja -DCMAKE_BUILD_TYPE=Release `
    "-DHOUDINI_ROOT=$HoudiniRoot" "-DCMAKE_INSTALL_PREFIX=$install"
if ($LASTEXITCODE -ne 0) { throw 'Houdini plugin configuration failed.' }
& cmake --build $build --parallel $Jobs
if ($LASTEXITCODE -ne 0) { throw 'Houdini plugin build failed.' }
& cmake --install $build
if ($LASTEXITCODE -ne 0) { throw 'Houdini plugin installation failed.' }
& "$repo/build/deps/x64-windows/tools/python3/python.exe" "$PSScriptRoot/houdini/stage_package.py" `
    --install $install --houdini $HoudiniRoot --worker $worker
if ($LASTEXITCODE -ne 0) { throw 'Houdini package staging failed.' }
Write-Host "Houdini package prepared: $install/moonray.json"
