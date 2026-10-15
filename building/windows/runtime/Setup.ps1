# SPDX-License-Identifier: Apache-2.0
# Dot-source this file to use this bundle's tools and Python modules.
$moonrayRuntimeRoot = $PSScriptRoot
$moonrayRuntimePaths = @("$moonrayRuntimeRoot/bin", "$moonrayRuntimeRoot/lib",
    "$moonrayRuntimeRoot/python", "$moonrayRuntimeRoot/python/DLLs")
$env:PATH = (($moonrayRuntimePaths + ($env:PATH -split ';')) | Select-Object -Unique) -join ';'
$env:RDL2_DSO_PATH = "$moonrayRuntimeRoot/rdl2dso"
$env:MOONRAY_CLASS_PATH = "$moonrayRuntimeRoot/coredata"
$env:PXR_PLUGINPATH_NAME = "$moonrayRuntimeRoot/plugin/pxr;$moonrayRuntimeRoot/lib/usd;$moonrayRuntimeRoot/plugin/usd"
$env:PXR_USD_WINDOWS_DLL_PATH = ($moonrayRuntimePaths -join ';')
$env:ARRAS_SESSION_PATH = "$moonrayRuntimeRoot/sessions"
$env:PYTHONHOME = "$moonrayRuntimeRoot/python"
$env:PYTHONPATH = "$moonrayRuntimeRoot/python/Lib/site-packages"
$env:PYTHONNOUSERSITE = '1'
