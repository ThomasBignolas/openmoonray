# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$HoudiniDirectory,
    [switch]$Xpu
)
$ErrorActionPreference = 'Stop'
$hython = Join-Path $HoudiniDirectory 'bin/hython.exe'
if (!(Test-Path -LiteralPath $hython)) { throw 'HoudiniDirectory must contain bin/hython.exe.' }
$out = Join-Path $PSScriptRoot ('test-results/' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
$prefs = Join-Path $out 'prefs21.0'
& (Join-Path $PSScriptRoot 'Install.ps1') -PreferenceDirectory $prefs
$previousPrefs = $env:HOUDINI_USER_PREF_DIR
$previousNoEnv = $env:HOUDINI_NO_ENV_FILE
$previousThreads = $env:HOUDINI_MAXTHREADS
try {
    $env:HOUDINI_USER_PREF_DIR = $prefs
    $env:HOUDINI_NO_ENV_FILE = '1'
    $threads = [Math]::Max(1, [Math]::Min(4, [Environment]::ProcessorCount - 1))
    $env:HOUDINI_MAXTHREADS = "$threads"
    $testArgs = @((Join-Path $PSScriptRoot 'tests/validate_default_sphere.py'), '--out', (Join-Path $out 'images'))
    if ($Xpu) { $testArgs += '--extended' }
    & (Join-Path $PSScriptRoot 'worker/python/python.exe') (Join-Path $PSScriptRoot 'tests/run_bounded.py') `
        --threads $threads --memory-gb 6 --min-free-gb 6 --timeout 180 `
        --log (Join-Path $out 'render.log') --report (Join-Path $out 'resources.json') -- $hython @testArgs
    if ($LASTEXITCODE -ne 0) { throw "MoonRay smoke test failed. See $out" }
    Write-Host "MoonRay smoke test passed. Results: $out"
} finally {
    $env:HOUDINI_USER_PREF_DIR = $previousPrefs
    $env:HOUDINI_NO_ENV_FILE = $previousNoEnv
    $env:HOUDINI_MAXTHREADS = $previousThreads
}
