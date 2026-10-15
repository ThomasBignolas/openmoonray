MoonRay for Houdini - Windows portable package

Requirements
  Windows x64; AVX2-capable CPU; your own Houdini 21.0.729 installation.
  XPU: NVIDIA compute capability 7.5 or later (RTX 20-series or newer is
  the normal desktop target), and a driver supporting CUDA 13.3 PTX/OptiX 9.1.
  The current build was tested on an RTX 5060 Ti. Other GPUs need the smoke test.
  CUDA Toolkit, Visual Studio and a source checkout are not needed to run it.
  CPU rendering is available when XPU cannot be used.

Install
  1. Extract the ENTIRE ZIP to a permanent, writable folder on your PC.
  2. Open PowerShell in that folder and run:
       powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1
  3. Restart Houdini 21.0.729. MoonRay appears in Solaris and the MoonRay menu.

The installer changes only files in this bundle and your Houdini user package.
It does not require administrator access or change the machine execution policy.
It backs up any previous MoonRay package in package-backups/. Other renderers
and open Houdini sessions are left alone. If you move the folder, rerun Install.
For a custom Houdini preference directory, pass -PreferenceDirectory explicitly.

Test CPU, or CPU plus XPU, without opening a window:
  .\Test.ps1 -HoudiniDirectory 'C:\Program Files\Side Effects Software\Houdini 21.0.729'
  .\Test.ps1 -HoudiniDirectory 'C:\Program Files\Side Effects Software\Houdini 21.0.729' -Xpu
The test uses isolated preferences, at most four CPU threads, a 6 GB memory cap,
and requires 6 GB free memory. Images and logs go in test-results/.

Do not run Houdini from worker/Setup.ps1 or put worker DLLs on Houdini's PATH.
The host and render worker deliberately use separate USD/Python runtimes.
Scene files and project textures/caches are separate: copy them with your project
and use project-relative paths where practical. The package does not include ALab.

See docs/HOUDINI.md for features and remaining limitations, and worker/licenses/
for component notices. This is a tested integration snapshot, not certification
of every scene, GPU or Houdini build. A different Houdini build requires a rebuild.
