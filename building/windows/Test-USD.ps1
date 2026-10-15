# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot/../..").Path
$env:PYTHONPATH = "$repo/build/deps-extra/lib/python"
& "$repo/build/deps/x64-windows/tools/python3/python.exe" "$PSScriptRoot/tests/test_usd.py" $repo
if ($LASTEXITCODE -ne 0) { throw 'Installed USD runtime test failed.' }
