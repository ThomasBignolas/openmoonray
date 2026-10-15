@echo off
rem SPDX-License-Identifier: Apache-2.0
set "PATH=%~dp0bin;%~dp0lib;%~dp0python;%~dp0python\DLLs;%PATH%"
set "RDL2_DSO_PATH=%~dp0rdl2dso"
set "MOONRAY_CLASS_PATH=%~dp0coredata"
set "PXR_PLUGINPATH_NAME=%~dp0plugin\pxr;%~dp0lib\usd;%~dp0plugin\usd"
set "PXR_USD_WINDOWS_DLL_PATH=%~dp0bin;%~dp0lib;%~dp0python;%~dp0python\DLLs"
set "ARRAS_SESSION_PATH=%~dp0sessions"
set "PYTHONHOME=%~dp0python"
set "PYTHONPATH=%~dp0python\Lib\site-packages"
set "PYTHONNOUSERSITE=1"
