# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param(
    [string]$PreferenceDirectory = "$env:USERPROFILE/Documents/houdini21.0",
    [string]$InstallationDirectory = ''
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path "$PSScriptRoot/../..").Path
if (!$InstallationDirectory) { $InstallationDirectory = Join-Path $repo 'build/windows/houdini/install' }
$package = Join-Path $InstallationDirectory 'moonray.json'
if (!(Test-Path -LiteralPath $package)) { throw 'Run Build-Houdini.ps1 first.' }
$null = Get-Content -LiteralPath $package -Raw | ConvertFrom-Json
$destinationDirectory = Join-Path $PreferenceDirectory 'packages'
$destination = Join-Path $destinationDirectory 'moonray.json'
New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
if (Test-Path -LiteralPath $destination) {
    $backupDirectory = Join-Path $repo 'build/windows/houdini/package-backups'
    New-Item -ItemType Directory -Force -Path $backupDirectory | Out-Null
    Copy-Item -LiteralPath $destination -Destination (Join-Path $backupDirectory ("moonray-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss-fff')))
}
Copy-Item -LiteralPath $package -Destination $destination
Write-Host "Installed MoonRay package: $destination"
Write-Host 'Restart Houdini to load it. Disable MoonRay by removing this package JSON.'
