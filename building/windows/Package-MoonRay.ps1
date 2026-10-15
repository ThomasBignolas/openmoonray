# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param(
    [string]$InstallPrefix = "$PSScriptRoot/../../build/windows/install-validation",
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/Enter-BuildEnvironment.ps1"
$packageRepo = (Resolve-Path "$PSScriptRoot/../..").Path
$packagePython = "$packageRepo/build/deps/x64-windows/tools/python3/python.exe"
$packageCrt = Join-Path $env:VCToolsRedistDir 'x64/Microsoft.VC143.CRT'
$ErrorActionPreference = 'Continue'
& $packagePython "$PSScriptRoot/package_runtime.py" --install $InstallPrefix `
    --output $OutputDirectory --crt $packageCrt --cmake (Get-Command cmake.exe).Source `
    --dumpbin (Get-Command dumpbin.exe).Source
if ($LASTEXITCODE -ne 0) { throw 'Windows runtime packaging failed; inspect the retained staging directory.' }
