# Copyright 2026
# SPDX-License-Identifier: Apache-2.0
# Dot-source this script to enable the x64 Visual Studio toolchain in this shell.
$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$vsRoot = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsRoot) { throw 'Visual Studio 2022 with the x64 C++ build tools is required.' }
$vcvars = Join-Path $vsRoot 'VC/Auxiliary/Build/vcvars64.bat'
# Import the batch environment without printing it. This also works in hosts
# that supply both PATH and Path, which Enter-VsDevShell rejects.
$activeCompiler = Get-Command cl.exe -ErrorAction SilentlyContinue
if (!$activeCompiler -or $env:VSCMD_ARG_TGT_ARCH -ne 'x64' -or
    !$activeCompiler.Source.StartsWith($vsRoot, [StringComparison]::OrdinalIgnoreCase)) {
    $environment = & $env:ComSpec /d /c "`"$vcvars`" >nul && set"
    if ($LASTEXITCODE -ne 0) { throw 'Visual Studio environment initialization failed.' }
    $importedKeys = @{}
    foreach ($entry in $environment) {
        if ($entry -match '^([^=]+)=(.*)$') {
            if ($importedKeys.ContainsKey($matches[1])) { continue }
            $importedKeys[$matches[1]] = $true
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
            if ($matches[1] -ieq 'PATH') { $env:PATH = $matches[2] }
        }
    }
}
$cmakeRoot = Join-Path $vsRoot 'Common7/IDE/CommonExtensions/Microsoft/CMake'
$buildPaths = @("$cmakeRoot/CMake/bin", "$cmakeRoot/Ninja") + ($env:PATH -split ';')
$env:PATH = ($buildPaths | Select-Object -Unique) -join ';'
