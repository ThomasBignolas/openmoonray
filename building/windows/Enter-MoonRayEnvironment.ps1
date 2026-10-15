# SPDX-License-Identifier: Apache-2.0
# Dot-source after Enter-BuildEnvironment.ps1 for tools from the native build.
param([string]$InstallPrefix)

$moonrayRepo = (Resolve-Path "$PSScriptRoot/../..").Path
$moonrayBuild = "$moonrayRepo/build/windows/native"
$moonrayDeps = "$moonrayRepo/build/deps/x64-windows"
$moonrayDllDirs = @()
if (!$InstallPrefix -and (Test-Path $moonrayBuild)) {
    # Plugins are loaded by absolute path. Only their shared library dependencies
    # need PATH entries; adding every plugin directory can exceed Windows limits.
    # rg does not follow the generated header junctions.
    $moonrayDllDirs = @(& rg --files --no-ignore -g '*.dll' $moonrayBuild |
        Where-Object { $_ -match '[\\/]lib[\\/]' -or $_ -match '[\\/]mcrt_messages[\\/]' -or
            $_ -match '[\\/]mcrt_computation[\\/]computation[\\/]' } |
        ForEach-Object { Split-Path -Parent $_ } | Sort-Object -Unique)
}
$moonrayToolDirs = @(
    "$moonrayBuild/moonray/cmd/raas_cmd/moonray",
    "$moonrayBuild/scene_rdl2/cmd/rdl2_cmd/rdl2_json_exporter",
    "$moonrayBuild/scene_rdl2/cmd/rdl2_cmd/rdl2_compare",
    "$moonrayBuild/hdMoonray/cmd/hd_cmd/hd_render",
    "$moonrayBuild/hdMoonray/cmd/hd_cmd/hd_usd2rdl"
)
$moonrayDsoDir = "$moonrayBuild/rdl2dso"
$moonrayPluginDir = "$moonrayBuild/usd_plugins/Release"
$moonrayClassDirs = "$moonrayBuild/moonray/dso;$moonrayBuild/moonshine/dso;$moonrayBuild/moonshine_usd/dso"
$moonrayPythonDir = "$moonrayBuild/scene_rdl2/mod/python/py_scene_rdl2"
$moonraySessionDir = "$moonrayBuild/hdMoonray/sessions"
$env:REZ_MOONRAY_ROOT = $moonrayBuild.Replace('\', '/')
$moonrayCudaDirs = @()
if (!$InstallPrefix -and (Test-Path "$moonrayBuild/CMakeCache.txt")) {
    $moonrayCudaMatch = Select-String -LiteralPath "$moonrayBuild/CMakeCache.txt" -Pattern '^CUDAToolkit_BIN_DIR:PATH=(.+)$'
    if ($moonrayCudaMatch) {
        $moonrayCudaBin = $moonrayCudaMatch.Matches[0].Groups[1].Value
        $moonrayCudaDirs = @("$moonrayCudaBin/x64", $moonrayCudaBin)
    }
}
if ($InstallPrefix) {
    $moonrayInstalled = (Resolve-Path -LiteralPath $InstallPrefix).Path
    $env:REZ_MOONRAY_ROOT = $moonrayInstalled.Replace('\', '/')
    $moonrayToolDirs = @("$moonrayInstalled/bin")
    $moonrayDsoDir = "$moonrayInstalled/rdl2dso"
    $moonrayPluginDir = "$moonrayInstalled/plugin/pxr"
    $moonrayClassDirs = "$moonrayInstalled/coredata"
    $moonrayPythonDir = "$moonrayInstalled/python/lib/python3.11"
    $moonraySessionDir = "$moonrayInstalled/sessions"
    # Switching to the installation must not leave build-tree binaries or USD
    # metadata ahead of the installed plugins in the current process.
    foreach ($name in @('PATH', 'PXR_PLUGINPATH_NAME', 'PYTHONPATH', 'ARRAS_SESSION_PATH')) {
        $nativePrefix = $moonrayBuild.Replace('/', '\').TrimEnd('\') + '\'
        $paths = [Environment]::GetEnvironmentVariable($name, 'Process') -split ';' |
            Where-Object { $_ -and !$_.Replace('/', '\').StartsWith($nativePrefix, [StringComparison]::OrdinalIgnoreCase) }
        [Environment]::SetEnvironmentVariable($name, ($paths -join ';'), 'Process')
    }
}
$moonrayRuntimeDirs = $moonrayToolDirs + @(
    "$moonrayDeps/bin",
    "$moonrayDeps/tools/openimageio",
    "$moonrayRepo/build/tools/tbb/bin/intel64/vc14",
    "$moonrayRepo/build/deps-extra/bin",
    "$moonrayRepo/build/deps-arras/bin",
    "$moonrayRepo/build/deps-extra/lib",
    "$moonrayRepo/build/tools/oidn-2.3.3.x64.windows/bin"
) + $moonrayDllDirs + $moonrayCudaDirs
function Add-MoonRaySearchPaths([string[]]$NewPaths, [string]$CurrentPaths) {
    $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $paths = foreach ($entry in ($NewPaths + ($CurrentPaths -split ';'))) {
        if ($entry -and $seen.Add($entry.Replace('/', '\').TrimEnd('\'))) { $entry }
    }
    return ($paths -join ';')
}
$env:PATH = Add-MoonRaySearchPaths $moonrayRuntimeDirs $env:PATH
$env:RDL2_DSO_PATH = $moonrayDsoDir
$env:PYTHONHOME = "$moonrayDeps/tools/python3"
$env:PYTHONPATH = Add-MoonRaySearchPaths @($moonrayPythonDir, "$moonrayRepo/build/deps-extra/lib/python", "$moonrayDeps/lib/python3.11/site-packages") $env:PYTHONPATH
$env:PXR_PLUGINPATH_NAME = Add-MoonRaySearchPaths @($moonrayPluginDir) $env:PXR_PLUGINPATH_NAME
$env:MOONRAY_CLASS_PATH = $moonrayClassDirs
$env:ARRAS_SESSION_PATH = Add-MoonRaySearchPaths @($moonraySessionDir) $env:ARRAS_SESSION_PATH
