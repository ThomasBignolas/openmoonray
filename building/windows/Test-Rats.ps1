# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param(
    [string]$TestRegex = 'moonray/geometry/sphere',
    [ValidateSet('scalar', 'vector', 'default')]
    [string]$Mode = 'scalar',
    [ValidateSet('Render', 'Diff', 'RenderAndDiff')]
    [string]$Stage = 'RenderAndDiff',
    [string]$CanonicalDirectory = $env:RATS_CANONICAL_DIR,
    [ValidateRange(1, 1024)]
    [int]$Threads = 4,
    [ValidateRange(1, 86400)]
    [int]$TimeoutSeconds = 600,
    [switch]$List
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Enter-BuildEnvironment.ps1"
. "$PSScriptRoot/Enter-MoonRayEnvironment.ps1"
$ratsRepo = (Resolve-Path "$PSScriptRoot/../..").Path
$ratsBuild = "$ratsRepo/build/windows/native"
if (-not (Test-Path "$ratsBuild/rats/CTestTestfile.cmake")) {
    throw 'Configure the native build with BUILD_RATS=ON first.'
}
if (-not $List) {
    if ($Stage -ne 'Render') {
        if (-not $CanonicalDirectory -or -not (Test-Path -LiteralPath $CanonicalDirectory -PathType Container)) {
            throw 'Image comparison requires an existing trusted RATS canonical directory. Supply -CanonicalDirectory, or use -Stage Render to check rendering alone.'
        }
        $env:RATS_CANONICAL_DIR = (Resolve-Path -LiteralPath $CanonicalDirectory).Path
    }
    if ($Stage -ne 'Diff') {
        $pointerFiles = @(& rg -l --fixed-strings 'version https://git-lfs.github.com/spec/v1' "$ratsRepo/rats/assets")
        if ($pointerFiles.Count) {
            throw "RATS assets are still Git LFS pointers. Run git -C rats lfs pull first ($($pointerFiles.Count) files missing)."
        }
    }
}
$env:RATS_MOONRAY_THREADS = "$Threads"
$stageLabel = switch ($Stage) {
    'Render' { '^render$' }
    'Diff' { '^diff$' }
    'RenderAndDiff' { '^(render|diff)$' }
}
$ctestArgs = @('--test-dir', $ratsBuild, '--output-on-failure', '--no-tests=error',
    '-L', '^rats$', '-L', "^$Mode$", '-L', $stageLabel, '-R', $TestRegex,
    '--timeout', $TimeoutSeconds)
if ($List) { $ctestArgs += '-N' }
$ErrorActionPreference = 'Continue'
& ctest @ctestArgs
if ($LASTEXITCODE -ne 0) { throw 'RATS tests failed. See Testing/Temporary/LastTest.log in the native build.' }

