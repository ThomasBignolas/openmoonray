# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Client,
    [string]$HoudiniDirectory = 'C:/Houdini21',
    [string]$Scene
)
$ErrorActionPreference = 'Stop'
$clientPath = (Resolve-Path -LiteralPath $Client).Path
$houdiniPath = (Resolve-Path -LiteralPath $HoudiniDirectory).Path
if (!(Test-Path -LiteralPath "$clientPath/prefs21.0/packages/moonray.json")) {
    throw 'Run Classroom.ps1 prepare first and pass its output directory as -Client.'
}
$env:HOUDINI_USER_PREF_DIR = "$clientPath/prefs21.0"
$env:HOUDINI_NO_ENV_FILE = '1'
$arguments = @()
if ($Scene) { $arguments = @((Resolve-Path -LiteralPath $Scene).Path) }
# The requested artist application is visible; worker/coordinator processes are
# started separately by the user and never installed as services.
& "$houdiniPath/bin/houdini.exe" @arguments
