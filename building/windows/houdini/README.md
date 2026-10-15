# MoonRay for Houdini on this workstation

Installed for **Houdini 21.0.729, Windows x64**, using local CPU or NVIDIA XPU rendering.
No Linux machine, administrator access, or render server is needed.

For another Windows PC, see [the portable package guide](PORTABLE.md). The bundle
includes a user-level installer that rewrites its host and worker paths after
extraction; copying the current workstation's package JSON alone is insufficient.

## Worker reliability and recovery

The October 15 reliability update uses Arras's existing asynchronous send queue
to serialize scene updates, image credits and interactive controls. Concurrent
synchronous sends reproduced a protocol-framing error and crash in an isolated
test; the same 64-message, four-sender test passes through the SDK queue.
This fixes a demonstrated transport hazard. It does not establish the cause of
every earlier ALab failure.

Unexpected worker exits, connection errors, failed startup and failed scene
sends now set Houdini's render error status and display a failure annotation.
Errors stay set until the renderer is restarted or its session settings change.
Use **MoonRay > Restart Live Render** (or the **Restart IPR** shelf tool) to retry
after correcting the cause. **Stop Live Render / Stop IPR** returns to Houdini's
viewport renderer. Both actions are now exposed in the menu and shelf. Batch Husk
reports failure instead of waiting indefinitely. Session replacement and
destruction join SDK callbacks while their state still exists, without holding
the image-callback mutex.

Evidence is under `build/windows/houdini/worker-disconnect-check`:

- `before/validation.json`: Husk still waiting 12 seconds after worker loss.
- `after/validation.json`: fatal error and exit code 1 within 0.19 seconds of
  the same injected worker loss.
- `startup/validation.json`: a deliberately missing worker is named in the log
  and causes a nonzero Husk exit, using test-only preferences/session files.
- `lifecycle/validation.json`: the real host delegate renders, restarts,
  detects a killed worker, restarts again with matching image content, and
  safely shuts down with a queued frame. This test needs no visible Houdini UI.
- `healthy/validation.json`: all 30 small CPU/XPU primitive, material and
  animation checks still pass.
- `outputs/validation.json`: all 12 ACES, raw normal, lossless Cryptomatte and
  deep EXR checks pass through the updated transport.
- `arras-tests.log`: eight local SDK tests pass, including concurrent sends.

`validate_worker_disconnect.py` runs the worker-loss test by default; `--startup`
tests failed startup. For the lifecycle test, build the explicit CMake target
`test_arras_renderer_lifecycle` and pass its path with `--lifecycle`, plus a small
RDLA file with `--scene`. Run these tests under `run_bounded.py`. Fault injection
requires exactly one `execComp.exe` child of the test process and never targets
workers belonging to an open Houdini session.

## Unassigned geometry and USD primitives

A sphere made in Solaris > SOP Create does not require a material to be visible.
MoonRay already supplies a gray `UsdPreviewSurface` fallback, respecting authored
`displayColor` and `displayOpacity`. The missing-sphere bug was in geometry
translation: Houdini's default Sphere SOP exports a USD `Sphere`, which the
legacy render delegate did not receive as a mesh under Hydra 2. Assigning a
material did not fix it. The earlier demos explicitly used polygon spheres.

The October 15 integration now connects OpenUSD's
[implicit-surface conversion](https://raw.githubusercontent.com/PixarAnimationStudios/OpenUSD/v25.05/pxr/imaging/hdsi/implicitSurfaceSceneIndex.cpp)
for spheres, cubes, cones, cylinders, capsules and planes. Dependency forwarding
propagates changes such as radius to the generated mesh. The source USD and
SOP geometry remain editable in their original form.

`validate_default_sphere.py --extended` checks actual SOP Create sphere exports,
unassigned and assigned materials, radius animation through a persistent render
delegate, and a small CPU/XPU grid of all six primitive types. Evidence is in
`build/windows/houdini/default-sphere-check/after2/validation.json` (30 checks).
The grid uses Polygon Preview to bound tessellation; the individual spheres and
animation use ordinary subdivision. The initial missing-geometry reproduction
is retained in `before`. The earlier orthographic grid attempt in `after` failed
image checks and its XPU attempt ran out of accelerator memory; those results
are preserved. Separate flat-mesh camera tests now pass perspective and
orthographic framing, aperture offsets, and an explicit clipping range against
USD's own projection matrices (`camera-check/after/validation.json`, nine checks).
The dense primitive-grid failure remains unresolved; the passing camera checks
do not certify every subdivision, interactive editing or instancing combination.

## Startup and texture handling

Standard `UsdUVTexture` networks now get filtering footprints directly from
the Hydra material translator, even without a Color Management LOP. This covers
the `st` primvar and chains of `UsdTransform2d`, including sampled animation.
Explicit footprints are preserved. Other UV sets and procedural coordinate
generators retain the zero-footprint fallback until their derivatives can be
represented correctly. The optional color preparation node remains responsible
for color-space conversion and texture generation.

The Windows worker raises its C runtime stream capacity from 512 to 8192 before
creating the texture system. The Render Settings texture file-handle control
still determines the OIIO cache limit. Previously, requesting thousands of
handles could still leave the cache capped at about 442 on this workstation,
causing repeated opens and texture errors in ALab.

Render Settings > Execution includes **Polygon Preview** and **Detailed Render
Statistics**, with the usual authoring controls. An authored Polygon Preview
value overrides viewport complexity; it changes subdivision geometry, so disable
it for final subdivision renders. Neither control is automatically authored in
existing scenes. `prepare_alab_interactive.py` enables them in its separate
preview HIP without modifying the original scene.

With `HDM_LOG_FILE` enabled, the delegate records the first image received after
each scene submission. This measures scene-send-to-image latency; it excludes
Houdini startup, USD translation and viewport display. `benchmark_houdini_scene.py`
also records elapsed time from starting Husk. Its memory/file-cache overrides
apply only in the test process. The script never saves over its source HIP.

Small regression evidence is under
`build/windows/houdini/alab-check/preview-fix`: `small4/validation.json` checks
preview controls, `texture-unit/validation.json` demonstrates 700 simultaneously
open textures after the stream fix, and `footprints-after/validation.json` checks
standard, transformed and animated UVs, explicit overrides and scalar/vector/XPU
renders without color preparation. The uncorrected checker read 3 MB of texture
pixels; the corrected case read 240 KB and averaged to the expected gray.
These are small-scene measurements, not an ALab startup-speed guarantee.

Full ALab validation is deferred while the workstation is in use. Earlier warm
filesystem-cache timings are not a controlled before/after speed comparison.
The interrupted full-scene tests and original worker/protocol failures remain
unresolved by these small checks.

## Color management and ACES

**MoonRay > Create Render Setup** now adds a **MoonRay Color Management** LOP.
For an existing scene, select the final LOP and use **MoonRay > Create Color Management**
(also available in the Solaris Tab menu). Connect it after materials, lights,
AOVs and Render Settings, before the render ROP. New materials and lights made
with the MoonRay shelf are inserted upstream of this preparation node.
Existing HIP files keep their previous appearance until this node is added.

| Control location | Available controls |
| --- | --- |
| Color Management > Color | OCIO configuration, rendering space (default ACEScg), source space for untagged scene colors, linear output space, custom EXR chromaticities |
| Textures and Mipmaps | Cache location, generate/reuse or require prepared cache, mipmap filter, float/half precision, tile size, preparation threads, premultiplied input handling, HDR ringing reduction |
| Texture Sampling | Global override for path default, nearest, bilinear, trilinear or anisotropic lookup; blur and maximum anisotropy |
| Overrides | Source color space, color/data usage and mipmap filter selected by USD prim and attribute patterns |
| Native ImageMap > Color and Filtering | Per-texture source space, usage, mipmap filter, lookup filter, blur and anisotropy |

An empty configuration field uses Houdini's existing `OCIO` environment setting;
the integration does not replace the school/studio configuration. Color textures,
material swatches and light colors are prepared in the rendering space.
USD light color temperature is converted from its defined linear Rec.709 basis.
Color transforms occur **before** mipmap filtering. Alpha is preserved; normal,
roughness, displacement and other data maps use raw float32 caches. A texture
shared by color and data consumers receives separate prepared branches.

Input precedence is the last matching override, USD color-space metadata,
explicit texture controls, USD UV Texture's source setting, identifiable image
metadata, then OCIO file rules. Set a source explicitly when an asset's tagging
is ambiguous. `Raw / Data` means no RGB conversion; use the actual linear color
space for a linear color texture that needs a change of primaries.
Overrides use shell-style path wildcards, not Solaris selection expressions.

Prepared textures are tiled `.tx` files under `$HIP/.moonray/textures` by default.
The cache key includes source path/size/modification time, OCIO configuration,
spaces and generation options. Sources are preserved. Changing a filter creates
a separate cache entry. **Require Prepared Cache** allows rendering from an
already prepared, read-only cache and fails clearly if an entry is missing.
UDIM tiles and authored texture time samples are supported. When moving exported
USD to another machine, make its prepared texture and USD overlay cache paths
accessible there. Native and nested geometry instances remain instanced;
converted instance materials are composed through small cached USD overlays.

MoonRay's sampler requires tiled mipmapped images. Nearest and bilinear controls
disable mip *selection*, while retaining the pyramid on disk. Standard `st`
coordinates and affine UsdTransform2d graphs supply UV footprints for filtering.
Custom procedural UV generators do not yet propagate automatic footprints;
explicit blur is available. Lookup overrides apply to ImageMap and UsdUVTexture.
ProjectCameraMap and light textures receive color preparation, but retain their
own lookup behavior. Arbitrary third-party shader networks and color primvars
inside instance proxies are not certified by these tests.

Use Houdini's normal OCIO display/view controls for viewing. EXRs stay linear;
beauty/color AOVs can use a different linear output space, while utility AOVs
and Cryptomatte remain raw. Deep output currently requires the rendering space.
Flat EXRs use a small `MoonRayEXR` image adapter around Houdini's stock OIIO writer
to preserve typed chromaticities; native deep outputs receive the same primaries
through MoonRay's EXR metadata API. Render Settings Pattern selects the settings
prims receiving working-space metadata; scene and product preparation is global
to this LOP's input stage, so use separate branches for different render spaces.

Validation scripts are `validate_color_pipeline.py`, `validate_color_render.py`
and `validate_color_workflow.py`. They check OCIO numeric agreement, raw data,
UDIMs, mipmaps, animated UV footprints, material instancing, scalar/vector/XPU
renders, flat/deep EXR metadata and saved Houdini scene rendering. Evidence is
under `build/windows/houdini/color-check`. These small tests do not certify the
full ALab scene, arbitrary shader graphs, or interactive display appearance.

Upstream MoonRay already includes OCIO viewing in `moonray_gui` and legacy
texture gamma controls. The Solaris input preparation and controls described
here are additions in this Windows integration. The earlier ALab PNG previews
use simple linear-to-sRGB conversion, not an ACES view transform.
See [Houdini color management](https://www.sidefx.com/docs/houdini/solaris/ocio.html)
and the [upstream MoonRay GUI](https://docs.openmoonray.org/user-reference/tools/moonray-gui/).

## USD light and shadow linking

The October 14 update connects OpenUSD's standard light-linking scene index for
USD 25.05 and newer. This resolves USD light, shadow and filter collections into
the categories expected by MoonRay's delegate, while preserving categories from
legacy scene delegates. Shadow exclusions are now evaluated independently of
whether the same light illuminates the object. Both fixes apply to arbitrary
scenes; no ALab paths, light values or geometry removals are in the renderer.

`validate_usd_linking.py` creates twelve small scenes without external assets.
Eleven image checks cover ordinary shadows, shadow include/exclude collections,
light exclusion, independent light/shadow links, native instances and point
instancers. Run it with Houdini's `hython`, then run it with the worker Python
and `--check` to validate the rendered images. Evidence is under
`build/windows/houdini/shadow-link-check/complete/validation.json`.
The disposable live-edit harness has not completed a render and is not counted
as passing. Its startup failures and incomplete final attempt are preserved
under `shadow-link-check/live*`; batch validation does not certify live edits.

ALab also renders its authored sunlight with the original geometry and lights
intact. The small regression render and its beauty, utility and Cryptomatte
validation are in `shadow-link-check/alab-validation.exr` and
`shadow-link-check/alab-aov-validation.json`. This check uses low complexity
(polygon preview), without motion blur. Higher subdivision exceeded the previous
16 GB test budget and remains a separate large-scene validation task.
The larger full-material preview is in `alab-check/lighting-fixed`. It completes
and passes numerical AOV checks, but reports OpenImageIO texture-sampling errors.
These errors also occur in the small comparison. Their cause remains unresolved;
finite pixels and a successful process exit do not prove correct texture output.

Different links on individual instances sharing one prototype, nested instance
links and instance-proxy targets remain limitations. The delegate still applies
one category set to a prototype; the instance regression covers a uniformly
linked instancer, not distinct per-instance links. The new tests do not certify
light-filter rendering, volumes or GPU shadow-link parity.

## Start rendering

1. Restart Houdini, or double-click [Open-Demo.cmd](Open-Demo.cmd).
2. Open `build/windows/houdini/demo/MoonRay_Solaris_Demo.hip`.
3. In Solaris, select `/stage/RENDER_MOONRAY` and click **Render to Disk**.
4. The result is `moonray_demo.exr` beside the HIP, with beauty RGBA, normal and depth parts.

The demo contains editable geometry, three area lights, a camera and native
MoonRay copper/ceramic materials. Edit shaders inside `/stage/moonray_materials`.
Quality controls are on `/stage/moonray_settings`, in the MoonRay section.
Pixel Samples is squared: 8 means 64 samples per pixel.

For live rendering, select the MoonRay render ROP and choose **MoonRay > Start /
Resume Live Render**. This selects the ROP's settings in the displayed USD stage.
Choose `/cameras/camera` for the demo view.
For denoising, enable both **Denoising** and **Use OIDN Denoising** in the viewport
render settings. The host viewport continues to use OIDN denoising.

## XPU rendering

On the **Render Settings LOP > Moonray > Execution** tab, set the control to
**Set or Create**, then choose **XPU (CPU + NVIDIA GPU)**. It applies to disk
renders and live Solaris rendering. The viewport also has an Execution Mode
preference; an authored Render Settings value takes precedence. **Auto (CPU)**
retains the upstream CPU selection. Existing HIP files keep their previous mode.
In the viewport's Render Display Options, select the intended **Render Settings
Prim**. A scene with several settings prims can otherwise preview a different
configuration from the Render ROP. The XPU demo includes a Configure Layer node
that selects `/Render/MoonRay/settings` as the stage's default render settings.
For an older Render Settings node without the new controls, select it and choose
**MoonRay > Refresh Render Settings Controls**. This preserves existing MoonRay
values, expressions and animation while updating its parameter folder.

**Local CPU Threads**, in the same Execution tab, limits the local render worker,
including CPU shading during XPU rendering. New Render Setups use four threads;
increase this for final renders or reduce it when using other applications.
Zero uses the automatic count after reserving cores. A changed limit reconnects
the local worker. This controls rendering threads, not a hard process CPU or
memory quota; loading and utility libraries can create additional threads.

XPU uses the NVIDIA GPU for surface ray intersections and keeps shading and
other work on the CPU. This workstation's RTX 5060 Ti, driver 610.62, CUDA 13.3
and OptiX 9.1 are the tested combination. The worker bundles the CUDA runtime
and compiled ray programs; no administrator installation is needed to run it.

The Windows build falls back to scalar CPU for reflected/refracted Cryptomatte,
overlapping dielectrics and deep volumes, preserving these features. Unsupported
GPU geometry and GPU initialization failures fall back to CPU vectorized mode.
Regular Cryptomatte, CryptoP/N/UV and hard-surface deep output work in XPU.
Check the render log for **GPU setup finished. Using GPU: ...** and GPU ray
utilization when confirming acceleration. Small scenes and shading/volume-heavy
shots may take as long or longer than CPU rendering; GPU use is not a speed guarantee.

The two-frame surface comparison at 144 samples has beauty mean absolute errors
below 0.00009 and maxima below 0.007. P/N/UV have a few silhouette-sample differences.
These are measured close matches, not certified pixel identity. The comparison
reports retain the full errors and acceptance thresholds.

The skin/hair/instances/VDB probe also executes on the GPU. At 576 samples its
beauty mean absolute errors are 0.0000904 and 0.0001019 (maxima below 0.0062).
The second frame narrowly exceeds the test's 0.0001 mean threshold; its failed
comparison is preserved in `xpu-shot-quality-check/image-validation.json`.
This does not establish exact CPU/GPU parity for complex shots.

A separate ready-to-use scene is saved at
`build/windows/houdini/xpu-installed-check/MoonRay_XPU_Demo.hip`.

A command-line render is also available:

```powershell
powershell -ExecutionPolicy Bypass -File building/windows/houdini/Render-Demo.ps1
```

## Using your own scenes

- Use the **MoonRay** main menu, or enable the **MoonRay** shelf using the
  shelf's **+ > Shelves** menu. Both expose the same 22 actions.
- **Create Render Setup** adds editable camera (if needed), Render Var,
  Render Product, Render Settings and USD Render ROP nodes. It starts at
  960 x 540 with 16 samples per pixel. Beauty, normal and depth go to
  `$HIP/render/moonray.$F4.exr`. The connected **MoonRay AOVs** node adds
  Cryptomatte, CryptoP, CryptoN and CryptoUV by default. Increase Pixel Samples
  for final renders.
- Inside a Material Library, press **Tab > MoonRay Material Builder**. It is
  available with Houdini's normal `*builder` menu filter. Dive into the builder
  and select **surface** to edit the DwaBaseMaterial's colour, roughness and
  other controls; use Tab inside for MoonRay textures and shaders. Its output
  is already connected. The upstream `Moonray BaseMaterial` asset has no
  parameters; use `DwaBaseMaterial` for a general surface shader.
- The material shortcuts create surface, glass, skin and volume builders in
  Material Library nodes. **Assign Material** adds an assignment LOP; choose
  the geometry and material paths there. Area, disk, dome and distant light
  shortcuts create standard editable Solaris light nodes.
- **Start / Resume Live Render** selects MoonRay in the viewport. **Pause
  Live Render** stops sampling while keeping the local render session alive.
  Resume starts sampling the current scene again. **Restart Live Render**
  recreates the viewport renderer. **Stop Live Render** returns to Houdini VK.
  **Use Render Setup in Viewport** selects the render ROP's settings without
  starting rendering. **Render Settings** selects
  the settings node; **Render to MPlay** and **Render to Disk** use the render ROP.
- Work in Solaris (`/stage`). Use a Material Library with the native MoonRay VOP
  nodes and Assign Material LOPs. The package installs 125 native MoonRay VOP
  assets plus the MoonRay AOVs and MoonRay Deep Output LOPs.
- Set the USD Render ROP renderer to **Moonray**, connect the scene and select
  its Render Settings primitive. Standard USD Render Product/Render Var nodes
  control files and AOVs, including light path expressions.
- Use native MoonRay materials or supported USD Preview Surface networks.
  Karma-specific and arbitrary MaterialX networks have not been validated.
- Cache volumes to VDB files before rendering. Direct in-memory Houdini SOP
  volume paths (`op:`) are not implemented by this delegate.
- MoonRay ramps preserve a separate interpolation mode per knot. Supported
  Houdini choices are Constant, Linear, Hermite (MoonRay Smooth), Catmull-Rom
  and Monotone Cubic. Bezier and B-Spline are not translated.

## Cryptomatte and compositing passes

Use **Tab > MoonRay AOVs** in Solaris, or **MoonRay > Create AOVs**. Connect it
after a Render Product and before the Render Settings / USD Render ROP.
New MoonRay Render Setups include this node. The Cryptomatte tab exposes:

- Object/mesh-part IDs, coverage, layer name and ID depth.
- **CryptoP**, **CryptoP0**, **CryptoN**, **CryptoB**, **CryptoRefP**,
  **CryptoRefN**, **CryptoUV** and **CryptoS**.
- Reflected and refracted variants of IDs and every enabled extension.

Utility Passes includes P, Wp, N, Ng, UV, camera depth and motion vectors.
Lighting includes an all-light LPE. Standard Render Var LOPs remain available
for custom LPEs, material AOVs and the original MoonRay RenderOutput controls.

The numbered Cryptomatte layers and embedded manifest are written to EXR when
the local worker finishes a frame. IDs and extension data stay 32-bit float.
The primary Cryptomatte plane is a coverage preview; the numbered affiliated
layers contain the actual IDs and data. These affiliated layers are disk-render
outputs, not individual live viewport AOVs.

In this build P/CryptoP are in render space; **Wp** is the ordinary world-position
pass. CryptoP0 reads a supplied world-space `p0` primvar and converts it to render
space. Reference passes use `ref_P` / `ref_N`; RefN can also be derived from RefP.
Supply reference/initial-position attributes on your cached geometry when needed.
The bridge now requests those attributes even if the material does not use them.

For reflected or refracted masks, also enable **Record Reflected Cryptomatte** or
**Record Refracted Cryptomatte** on the relevant mirror/glass material. These modes
require MoonRay's scalar execution path. Extension names match the core writer,
for example `CryptoReflectP00` and `CryptoRefractUV00`.

Point instances receive separate names of the form `/instancer/instance_0`.
Keep the USD instance ordering stable across frames when relying on those IDs.
Use polygon meshes for point-instancer prototypes in this tested workflow.
Nested instance identity and arbitrary authored-ID manifests are not certified.
CryptoS exports fragment sample data; Houdini checkpoint/resume is not enabled
by that toggle. This Cryptomatte transport supports the local single worker.
Enable the extensions and depth you need: each adds full-resolution buffers.

An editable example is saved separately as
`build/windows/houdini/aov-installed-check/MoonRay_AOV_Demo.hip`.
The original demo HIP is preserved.

## Deep EXR output

Select the USD Render ROP and choose **MoonRay > Create Deep Output**, or use
**Tab > MoonRay Deep Output** after Render Settings and before the render ROP.
The node attaches a separate deep Render Product to the chosen settings. Set
its filename (use `$F4` for sequences), choose **OpenEXR Deep** or **OpenDCX**,
and optionally include N, P and UV. RGB, alpha, front/back depth and native deep
IDs are included. P/N/UV and IDs retain float precision; RGB/alpha use the native
writer's half precision. Deep IDs are native channels, separate from Cryptomatte.

Use **Uniform Sampling** in MoonRay Render Settings. Deep output uses complete
per-pixel batch sampling on the local worker; flat-only renders retain the
progressive path. Unsupported adaptive/checkpoint/remote configurations report
an error. Set output paths on the Product nodes; leave the render ROP's global
output-image override empty when writing separate flat and deep files.

The worker writes deep files before reporting frame completion, and file-write
errors fail the Husk job. Existing flat beauty and Cryptomatte products continue
to be written alongside them. The AOV node automatically targets flat products.
An editable example is saved at
`build/windows/houdini/deep-installed-check/MoonRay_Deep_Demo.hip`.

Two-frame hard-surface and character/curve checks flatten closely to the flat
beauty (mean RGB differences below 0.000014 in the tested scene). OpenDCX masks
need a compositor that interprets those masks; ordinary OIIO flattening does not.
The cached VDB probe produces valid deep samples and much closer alpha after the
batch fix, but its flattened beauty still fails the strict surface comparison:
maximum RGB difference 0.043, mean below 0.00030. Deep volume compositing therefore
still needs validation for the shot. The failing comparison is preserved in
`deep-volume-batch-check/image-validation.json`; it is not counted as a pass.
Nuke 17.0v3 reads the tested flat utility/CryptoP/N/UV channels and evaluates
regular, reflected and refracted Cryptomatte selections, including empty results
for unknown IDs. A surface OpenEXR Deep read through DeepToImage matches the
flat render at 2,304 sampled channel locations (mean error 0.00000882,
maximum 0.000695). These checks use raw data reads. OpenDCX compositing,
volume-deep compositing, extension-aware CryptoP/N/UV extraction tools and Fusion
still need separate validation.

## Installation and maintenance

The user package is
`C:/Users/thomas.bignolas/Documents/houdini21.0/packages/moonray.json`.
The current reliability update loads the host plugin from
`build/windows/houdini/install-reliability-20261015`; earlier installations are
preserved for rollback. The local render
worker uses `build/windows/houdini/worker-preview-20261014`, an isolated copy of
the validated runtime with lossless Cryptomatte transport, native deep output,
XPU, texture filtering and Windows texture file-capacity updates.
Keep both directories in place. Existing Houdini installations and other renderer
packages are preserved. Disable MoonRay by removing its package JSON and
restarting Houdini.

This package deliberately loads only in Houdini **21.0.729**. A different
Houdini build needs a compatible SDK build and validation before changing that
version restriction. Rebuild and reinstall with:

```powershell
./building/windows/Build-Houdini.ps1
./building/windows/Install-Houdini.ps1
```

To select an already staged alternate installation, pass
`-InstallationDirectory build/windows/houdini/install-reliability-20261015`
to `Install-Houdini.ps1`. It backs up the existing package JSON before replacing
it. Restart Houdini to load the selected installation.

To reproduce the GPU build, install a compatible CUDA toolkit, obtain the
[NVIDIA OptiX headers](https://github.com/NVIDIA/optix-dev) at tag `v9.1.0`
(tested commit `f1f6dd803f3159992d248178f6e09421c6eb8b6d`) in
`build/tools/optix-9.1.0`, then run:

```powershell
./building/windows/Build-MoonRay.ps1 -WithArras -WithOptix -Targets grid_engine_tool,computation_engine_mcrt
./building/windows/Build-Houdini.ps1
```

`Build-Houdini.ps1` detects the GPU build and stages its CUDA DLL and PTX with
the worker. Omitting `-WithOptix` from a new MoonRay configuration creates a CPU
build. The original v8 runtime and `worker-deep` remain available separately.

The host plugin uses Houdini's USD/oneTBB libraries and declaration-only shader
DSOs. Executable MoonRay shaders run in a separate local worker. Do not put the
standalone runtime's USD/Python DLLs on Houdini's PATH or launch Houdini from
the standalone `Setup.ps1` environment.

Solaris background scene updates are disabled for this delegate to avoid a
Houdini update-thread stall. The separate MoonRay worker still renders
asynchronously. Windows pause/resume uses render messages instead of suspending
the worker process.

## Validation

Reports and test images are under `build/windows/houdini`:

- `plugin-inspection.json`: all four USD plugins load; all 125 HDAs instantiate.
- `demo/render-from-hip.json`: the saved HIP renders through its USD Render ROP
  using the installed user package, at 960 × 540.
- `demo/image-validation.json`: beauty RGBA, normal and depth checks, LPE output
  and a changing two-frame render through a persistent delegate.
- `demo/material-validation.json`: per-knot integer ramp interpolation is
  preserved through Houdini's material translation.
- `animation-render.log`: two frames with CPU OIDN denoising, with no MoonRay
  conversion errors or denoiser errors in the final run.
- `demo/workflow-validation.json`: native render setup, all four material
  shortcuts, all four light shortcuts, assignment and settings selection.
- `builder-validation.json`: the material builder's connected USD surface,
  editable shader parameters and a render with the builder assigned.
- `live-viewport.json` and `live-*.png`: visible viewport rendering, material
  updates, the MoonRay shelf, and pause/resume checks.
- `all-crypto-check/validation.json`: all extension types, reference attributes,
  108 EXR parts per frame, exact ID/manifest correspondence, coverage and animation.
- `crypto-optics-check/validation.json`: mirror/glass surface selection and all
  corresponding reflected/refracted extension planes.
- `crypto-geometry-check/validation.json`: separate masks for four point instances
  and curves, including two-frame updates.
- `aov-installed-check/workflow-validation.json` and `image-validation.json`:
  installed-package AOV node, controls, HIP reload, Render ROP, RGBA beauty,
  utility/LPE outputs and Cryptomatte extensions.
- `shot-smoke-check/render-report.json` and `image-validation.json`: native
  DwaSkinMaterial, HairMaterial_v3, mesh instances and cached VDB/BaseVolume
  in a small scene. Volume and motion-blur toggles produce measured image changes.
- `deep-release-check/image-validation.json` and `crypto-validation.json`:
  two native deep frames, sample/depth checks, float utility channels, flat beauty
  comparison and all existing Cryptomatte extensions rendered alongside them.
- `deep-release-only-check/image-validation.json`: deep-only animation, nonzero
  beauty and distinct object IDs without a flat Cryptomatte pass.
- `deep-release-dcx-check/image-validation.json`: OpenDCX sample and mask output.
- `deep-installed-check/workflow-validation.json` and `image-validation.json`:
  installed Deep Output node, enable/disable, correct product targeting, HIP
  reload, actual Render ROP output and flat/deep image checks.
- `deep-worker-failure-check/render-report.json`, `deep-invalid-check/render-report.json`
  and `deep-release-adaptive-check/render-report.json`: expected nonzero Husk exits
  for native write failure, unsupported deep results and unsupported sampling.
- `deep-volume-batch-check/image-validation.json`: preserved failing strict
  volume flatten comparison, as described above.
- `xpu-quality-check/image-validation.json`: actual GPU execution, two frames,
  CPU/GPU beauty and utility comparison, and regular Cryptomatte validation.
- `xpu-fallback-check/image-validation.json`: reflected/refracted Cryptomatte
  with XPU requested, verified against scalar CPU rendering.
- `xpu-workflow-check/workflow-validation.json` and `deep-validation.json`:
  native execution control, HIP reload, Render ROP and valid flat/deep output.
- `xpu-installed-check/workflow-validation.json`, `deep-validation.json` and
  `crypto-validation.json`: the same workflow using the normal installed package.
- `xpu-shot-quality-check/image-validation.json`: preserved complex-shot
  comparison, including the slight mean-error threshold failure described above.
- `../xpu-native-validation.json`: direct native command-line XPU render,
  finite nonzero pixels and 100% GPU utilization for the bundled ray queries.
- `xpu-integration-validation.json`: installed binary hashes, worker dependencies,
  report locations, source backup and remaining limitations.
- `xpu-viewport-final-validation.json`: visible rendering and material updates,
  with an active CUDA/OptiX context in the XPU worker. The pause state did not
  remain active in the automated HOM check, so the full UI test remains a failure.
- `reliability-installed-check/validation.json`: the updated installed package,
  settings refresh preserving animation, shared viewport/ROP settings, HIP reload
  and a small CPU render requesting two threads.
- `reliability-idle-ui4/validation.json`: visible CPU viewport start, persistent
  pause, resume, restart with a completed new frame, and return to Houdini VK.
  The earlier failed checks remain saved. `reliability-idle-ui3/worker-allocation.json`
  separately records the worker command line with `--cores 2`.
- `nuke-check/validation.json`: native Nuke Cryptomatte selections and OpenEXR
  surface DeepToImage comparison, with a saved standalone `.nk` example.

The viewport checks use a visible Houdini window and inspect actual rendered
images. The latest tests close their own window externally after saving a
separate session backup. Both `hou.exit()` and HScript quit from a Qt timer
caused shutdown crashes in the UI test harness. Earlier XPU edit/pause automation
failures are retained in `xpu-viewport-check7` and `xpu-viewport-check8`;
they are not counted as passing validations.

This is a working Windows integration for scene work and testing. Full feature
coverage and exact Linux image parity have not been certified. The tests do
not establish support for every Houdini feature or third-party shader.

For an environment/character/lookdev shot, the tested path is Solaris mesh and
curve geometry, native MoonRay materials, local CPU/XPU rendering and flat EXR
compositing passes. Large scene memory, dense production grooms, long sequences,
USD skeletal deformation, nested instance identity, displacement-heavy assets,
volume Cryptomatte and broader compositing workflows still need project
validation. The Nuke checks above cover small specific scenes; they do not
certify arbitrary production assets or every compositing operation.

Host OptiX denoising, distributed Cryptomatte merging, checkpoint/resume and DisplayFilter
shader networks are not connected through
this Houdini disk-render path. Their appearance in upstream parameter templates
does not establish support. The standalone renderer's capabilities and its RATS
results should not be treated as proof for those Houdini workflows.
