[CmdletBinding()]
param([string]$HoudiniRoot = 'C:/Houdini21')
$repo = (Resolve-Path "$PSScriptRoot/../../..").Path
$demo = Join-Path $repo 'build/windows/houdini/demo'
& "$HoudiniRoot/bin/hython.exe" "$PSScriptRoot/render_demo.py" $demo
if ($LASTEXITCODE -ne 0) { throw 'The MoonRay demo render failed. See the output above.' }
Write-Host "Rendered $demo/moonray_demo.exr"
