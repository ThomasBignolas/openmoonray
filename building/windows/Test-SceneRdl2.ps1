# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param(
    [ValidateSet('Release', 'Debug', 'RelWithDebInfo')]
    [string]$Configuration = 'Release',
    [string]$TestRegex = '^scenerdl2_scene_rdl2_tests$',
    [switch]$TestPython,
    [switch]$Native
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Enter-BuildEnvironment.ps1"
$repo = (Resolve-Path "$PSScriptRoot/../..").Path
$build = "$repo/build/windows/scene_rdl2-$Configuration"
if ($Native) { $build = "$repo/build/windows/native" }
$deps = "$repo/build/deps/x64-windows"
$runtime = if ($Configuration -eq 'Debug') { "$deps/debug/bin" } else { "$deps/bin" }
# rg does not follow the generated include junctions. DLLs live alongside
# their targets in the build tree; installed builds instead share one bin dir.
$dllDirs = & rg --files --no-ignore -g '*.dll' $build |
    ForEach-Object { Split-Path -Parent $_ } | Sort-Object -Unique
$env:PATH = ($dllDirs -join ';') + ";$runtime;$repo/build/tools/tbb/bin/intel64/vc14;$env:PATH"
if ($Native) {
    $env:PATH = "$repo/build/deps-extra/bin;$repo/build/deps-extra/lib;$repo/build/tools/oidn-2.3.3.x64.windows/bin;$env:PATH"
}
$ErrorActionPreference = 'Continue'
& ctest --test-dir $build --output-on-failure -R $TestRegex --timeout 300
if ($LASTEXITCODE -ne 0) { throw 'scene_rdl2 tests failed.' }
if ($TestPython) {
    $env:OMR_DLL_DIRS = (@($dllDirs) + $runtime + "$repo/build/tools/tbb/bin/intel64/vc14") -join ';'
    $env:PYTHONPATH = "$build/mod/python/py_scene_rdl2"
    if ($Native) { $env:PYTHONPATH = "$build/scene_rdl2/mod/python/py_scene_rdl2" }
    & "$deps/tools/python3/python.exe" "$PSScriptRoot/tests/test_scene_python.py" "$build/python-test-output"
    if ($LASTEXITCODE -ne 0) { throw 'scene_rdl2 Python tests failed.' }
}
