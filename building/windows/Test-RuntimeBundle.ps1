# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$BundleDirectory)
$ErrorActionPreference = 'Stop'
$bundleRoot = (Resolve-Path -LiteralPath $BundleDirectory).Path
# This is deliberately independent of Enter-BuildEnvironment and the checkout's DLLs.
$env:PATH = "$env:SystemRoot/System32;$env:SystemRoot"
$env:PYTHONPATH = ''
$env:PXR_PLUGINPATH_NAME = ''
$env:ARRAS_SESSION_PATH = ''
. "$bundleRoot/Setup.ps1"
$ErrorActionPreference = 'Continue'
& "$bundleRoot/python/python.exe" -X faulthandler "$PSScriptRoot/tests/test_runtime_bundle.py" $bundleRoot
if ($LASTEXITCODE -ne 0) { throw "Standalone Windows runtime validation failed (exit $LASTEXITCODE)." }
