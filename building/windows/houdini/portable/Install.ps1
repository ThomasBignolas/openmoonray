# SPDX-License-Identifier: Apache-2.0
[CmdletBinding()]
param(
    [string]$PreferenceDirectory = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'houdini21.0')
)
$ErrorActionPreference = 'Stop'
if (![Environment]::Is64BitOperatingSystem) { throw 'This package requires Windows x64.' }
$bundleRoot = $PSScriptRoot
$hostRoot = Join-Path $bundleRoot 'host'
$workerRoot = Join-Path $bundleRoot 'worker'
foreach ($required in @('host/plugin/hd_moonray.dll', 'host/bin/hydramoonray.dll',
                       'worker/bin/execComp.exe', 'worker/bin/computation_progmcrt.dll')) {
    if (!(Test-Path -LiteralPath (Join-Path $bundleRoot $required))) {
        throw "Incomplete bundle: $required is missing. Extract the entire archive first."
    }
}
$metadata = Get-Content -LiteralPath (Join-Path $bundleRoot 'bundle.json') -Raw | ConvertFrom-Json
$workerEnvironment = @{
    PATH = (@('bin','lib','python','python/DLLs') | ForEach-Object { Join-Path $workerRoot $_ }) -join ';'
    RDL2_DSO_PATH = Join-Path $workerRoot 'rdl2dso'
    MOONRAY_CLASS_PATH = Join-Path $workerRoot 'coredata'
    REZ_MOONRAY_ROOT = $workerRoot.Replace('\','/')
    PXR_PLUGINPATH_NAME = (Join-Path $workerRoot 'lib/usd') + ';' + (Join-Path $workerRoot 'plugin/usd')
    PYTHONHOME = Join-Path $workerRoot 'python'
    PYTHONPATH = Join-Path $workerRoot 'python/Lib/site-packages'
}
$workerEnvironment.PATH += ';' + (Join-Path $env:SystemRoot 'System32') + ';' + $env:SystemRoot
$utf8 = New-Object System.Text.UTF8Encoding($false)
foreach ($sessionFile in Get-ChildItem -LiteralPath (Join-Path $hostRoot 'sessions') -Filter '*.sessiondef' -File) {
    $session = Get-Content -LiteralPath $sessionFile.FullName -Raw | ConvertFrom-Json
    foreach ($computation in $session.computations.PSObject.Properties) {
        if ($computation.Name -ne '(client)') {
            $computation.Value | Add-Member -NotePropertyName environment -NotePropertyValue $workerEnvironment -Force
        }
    }
    [IO.File]::WriteAllText($sessionFile.FullName, ($session | ConvertTo-Json -Depth 25), $utf8)
}
$packagePath = Join-Path $hostRoot 'moonray.json'
$package = Get-Content -LiteralPath $packagePath -Raw | ConvertFrom-Json
foreach ($entry in $package.env) {
    if ($entry.PSObject.Properties.Name -contains 'MOONRAY_HOUDINI_ROOT') {
        $entry.MOONRAY_HOUDINI_ROOT = $hostRoot.Replace('\','/')
    }
}
$packageText = $package | ConvertTo-Json -Depth 12
[IO.File]::WriteAllText($packagePath, $packageText, $utf8)
$packages = Join-Path $PreferenceDirectory 'packages'
New-Item -ItemType Directory -Force -Path $packages | Out-Null
$destination = Join-Path $packages 'moonray.json'
if (Test-Path -LiteralPath $destination) {
    $backups = Join-Path $bundleRoot 'package-backups'
    New-Item -ItemType Directory -Force -Path $backups | Out-Null
    Copy-Item -LiteralPath $destination -Destination (Join-Path $backups ('moonray-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.json'))
}
[IO.File]::WriteAllText($destination, $packageText, $utf8)
Write-Host "Installed MoonRay for Houdini $($metadata.houdini_version)."
Write-Host "Package: $destination"
Write-Host 'Restart Houdini to load it. Keep this entire extracted folder in place.'
Write-Host 'If you move the folder, rerun this installer. No administrator access is needed.'
