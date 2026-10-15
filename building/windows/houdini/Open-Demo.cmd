@echo off
setlocal
set "DEMO=%~dp0..\..\..\build\windows\houdini\demo\MoonRay_Solaris_Demo.hip"
if not exist "C:\Houdini21\bin\houdinifx.exe" (
  echo Houdini 21.0.729 was not found in C:\Houdini21.
  pause
  exit /b 1
)
start "" "C:\Houdini21\bin\houdinifx.exe" -desktop Solaris "%DEMO%"
