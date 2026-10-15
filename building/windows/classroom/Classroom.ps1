# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('check','prepare','coordinator','worker','listen','probe','assets')][string]$Action,
    [Parameter(Mandatory=$true)][string]$Bundle,
    [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
)
$ErrorActionPreference = 'Stop'
$bundlePath = (Resolve-Path -LiteralPath $Bundle).Path
$python = Join-Path $bundlePath 'worker/python/python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Bundle must be an extracted MoonRay portable package.' }
# -E ignores Python environment settings inherited from a DCC or developer shell.
# -s prevents packages from the user's Python installation from changing the kit.
& $python -E -s (Join-Path $PSScriptRoot 'classroom.py') $Action.ToLowerInvariant() --bundle $bundlePath @Arguments
if ($LASTEXITCODE -ne 0) { throw "Classroom $Action returned $LASTEXITCODE. See the report above." }
