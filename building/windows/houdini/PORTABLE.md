# Using this integration on another Windows PC

Use the portable binary bundle for an artist workstation. A GitHub source
checkout is useful for development, but does not install the compiled plugin.

The snapshot targets Windows x64, an AVX2-capable CPU, and **Houdini 21.0.729**.
The host uses that Houdini build's USD and TBB ABI; another Houdini build needs a
separate compile and validation. Intel branding alone does not establish AVX2.

XPU is built with CUDA 13.3 and OptiX 9.1. Its PTX target is `sm_75`, so it needs
compute capability 7.5 or newer; modern desktop RTX cards are the usual target.
Use a driver supporting CUDA 13.3 PTX and OptiX 9.1, then run the included XPU
test. A generic CUDA 13.x minor-compatibility driver is not enough evidence for
PTX JIT compatibility. See NVIDIA's
[CUDA 13.3 notes](https://docs.nvidia.com/cuda/archive/13.3.1/cuda-toolkit-release-notes/)
and [compatibility limitations](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html).
Only the local RTX 5060 Ti has been exercised so far. CPU rendering remains an
option when XPU cannot be used.

Extract the full bundle to a permanent folder and run its `Install.ps1` in
PowerShell, then restart Houdini. The script writes a user package and rewrites
worker paths for that machine. It needs no administrator access, compiler or
CUDA Toolkit. Keep the extracted folder in place; rerun the installer if moved.
Project scenes, textures and caches must be transferred separately.

The bundle also contains `Test.ps1`. Supply `-HoudiniDirectory` with the local
Houdini installation; add `-Xpu` for CPU/XPU primitive and animation checks.
The tests run with isolated preferences and bounded resources.

To create a bundle from validated host and worker folders:

```powershell
python building/windows/houdini/package_portable.py `
  --host build/windows/houdini/install-reliability-20261015 `
  --worker build/windows/houdini/worker-preview-20261014 `
  --output 'build/windows/houdini/portable/MoonRay Houdini 21.0.729 Windows' --zip
```

The output directory and ZIP must be new. The package includes runtime component
notices, hashes, a CPU/XPU smoke test, and the user-level installer. It does not
include Houdini itself or ALab assets. The GitHub branch stores source and
packaging scripts; portable runtime ZIPs are separate distribution artifacts.
