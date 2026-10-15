# Native Windows port (in progress)

This directory contains the reproducible build scripts and focused regression
tests for the Windows x64 port. The native `moonray.exe` and its renderer DLLs
compile, link and pass startup layout checks. All 645 enabled upstream CPU/default
RATS render commands pass across scalar, vector and Hydra execution; five more
cases are disabled upstream. The v8 rerun completed on October 12, including the
Windows light-sampling hash fix and consistent FMA contraction. All 645 enabled
cases passed. The earlier v7 run and its interrupted/resumed batch audits remain
preserved separately.
The image audit finds no numeric NaNs; ten files contain diagnosed AOV infinities.
Render-command success is not image parity.
The main `hd_moonray` plugin also renders through native Arras workers. Installed
scalar and vector tests pass both an initial render and an interactive geometry
update. A standalone runtime bundle also passes these checks after relocation
to a directory containing spaces and a non-ASCII character, with only bundled
and Windows system directories in its environment. The packaged Windows client
also passed scalar/vector remote rendering and geometry updates against a real
Linux Arras worker in v7; that remote check has not been repeated for v8.
Trusted-reference image comparisons and Hydra acceptance
reference compatibility remain unfinished.

The Houdini integration now includes a separately staged NVIDIA XPU worker,
tested on an RTX 5060 Ti with CUDA 13.3 and OptiX 9.1. This does not change the
CPU v8 archive or imply GPU validation of all 645 RATS scenes. Build with
`Build-MoonRay.ps1 -WithArras -WithOptix`, then `Build-Houdini.ps1`.
See [Houdini XPU setup and validation](houdini/README.md#xpu-rendering).

## Requirements

- Visual Studio 2022 with Desktop Development with C++, Windows SDK, CMake and Ninja.
- Git, Git LFS for the RATS assets, and an x64 CPU with AVX2 support.
- PowerShell and network access for the first dependency bootstrap.
- A complete OpenMoonRay checkout at the superproject's pinned submodule revisions.

The source include links are generated as directory junctions in the build tree.
Windows Developer Mode and source checkout symlinks are not required. Some build
junctions point back into their parent tree; cleanup tools must not follow them.
The Houdini `moonray/moonray_dcc_plugins/houdini/otls` assets have filenames that
Windows cannot represent. Exclude that directory with Git sparse checkout when
checking out that submodule on Windows.

## Build and test

Run from the repository root:

```powershell
& .\building\windows\Bootstrap.ps1
& .\building\windows\Build-SceneRdl2.ps1 -Targets scenerdl2_scene_rdl2_tests,scenerdl2_common_math_tests,__scene_rdl2__,rdl2_print,rdl2_convert
& .\building\windows\Test-SceneRdl2.ps1 -TestPython
& .\building\windows\Test-SceneRdl2.ps1 -TestRegex '^scenerdl2_common_math_tests$'

. .\building\windows\Enter-BuildEnvironment.ps1
cmake -S building/windows/tests -B build/windows/platform-tests -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/windows/platform-tests
ctest --test-dir build/windows/platform-tests --output-on-failure
```

Set `PDEVUNIT_VERBOSE=1` to report each upstream test as it runs. An upstream test
executable also accepts a CppUnit test path as its first argument for diagnosis.
`Build-SceneRdl2.ps1 -ConfigureOnly` configures without compiling; omitting
`-Targets` builds the entire scene_rdl2 project. Release is the configuration
validated so far.

Renderer dependency builds are separate while the core port progresses:

```powershell
& .\building\windows\Build-Embree.ps1
& .\building\windows\Build-OpenVDB.ps1
& .\building\windows\Build-USD.ps1
& .\building\windows\Test-USD.ps1
```

Downloads, dependency installs and build outputs stay under `build/`. The scripts
pin source revisions or archive hashes. vcpkg dependencies use a pinned 2024
baseline; the newer vcpkg executable supports the installed VS 17.14 toolset.
Its generated Boost helper overlay handles the MSVC vc144 library suffix.
Embree and OpenVDB use legacy TBB 2020.3, matching the renderer's TBB APIs.

To export the source changes for another checkout:

```powershell
& .\build\deps\x64-windows\tools\python3\python.exe building/windows/package_source_changes.py build/windows/moonray-windows-source.zip
```

The exporter records the superproject and all 20 submodule revisions, includes
tracked patches and new source files, and checks every patch against its base
using temporary Git indexes. It verifies the archive contents and writes an
adjacent SHA-256 file and validation report. Existing archives are refused.
Follow `APPLY.txt` in the archive to apply it to a separate clean checkout, then
use the build instructions above. Patch applicability has been checked; a fresh
machine build remains unverified. Dependencies and runtime binaries are separate.

## Verified progress

On MSVC 19.44.35228, Windows x64, Release:

- Platform, logging, C++/ISPC math, framebuffer, utilities, cache and scene database
  DLLs compile and link.
- The ISPC scene-layout generator builds and runs. `rdl2_print` and `rdl2_convert`
  compile and link.
- All 207 upstream scene tests pass, including full/proxy plugin DLL loading,
  scene creation, ASCII/binary serialization and plugin exception recovery.
- All 103 upstream math tests pass, including the C++ and ISPC implementations.
- All 34 upstream grid utility tests pass, including shared framebuffer format
  conversions, affinity initialization and timeout recovery, packet encoding,
  framebuffer untile, argument parsing and CPU discovery.
- Sixteen focused tests pass: dependent DLL lookup from a path containing spaces,
  generated header links, Windows file operations, concurrent 128-bit atomics,
  64-bit serialization against golden byte sequences, renderer atomic pixel updates,
  binary-safe Lua embedding, runtime locking/time/process utilities, CPU/NUMA
  discovery and allocation, console socket fragmentation/reconnection, and COFF
  sampling-table embedding with byte and alignment verification, and renderer
  CPU feature/process-statistics queries through the native DLL, and thread CPU
  timing that excludes sleep.
  Windows shared-memory/semaphore tests additionally cover concurrent processes,
  read-only mappings, persistence after forced termination, attachment leases,
  safe cleanup, mutual exclusion, timeouts and lock recovery after process death.
  Renderer socket tests cover large writes, short reads, putback, moved socket
  ownership and peer disconnects. File watcher tests cover Unicode filenames,
  replacement by rename, deletion/recreation, filtering and blocking waits.
  Checkpoint file tests cover binary and concurrent copies, replacement of an
  existing output, error reporting and temporary-file removal after a crash.
- The native Python extension imports, creates scene objects, edits attributes,
  and round-trips scenes through ASCII and binary files.
- Embree 4.2 and OpenVDB 10.0.1 build and install against TBB 2020.3.
- USD 23.08 builds with Hydra imaging and Python. Installed ASCII/binary stage
  round-trips and discovery of the built-in Hydra Storm plugin pass.
- The denoiser, renderer common runtime, statistics, file-resource, texture sampler,
  shading and geometry DLLs build, as do all six PBR ISPC target groups.
- All six upstream hair shading tests pass through the native shading DLL,
  including C++/ISPC hybrid layout validation. On Windows the shading C++ and ISPC
  objects share one DLL to resolve their circular callbacks. The ray differential
  layout includes MSVC's base-class padding on both sides of the C++/ISPC boundary.
  The PBR, render-driver and application DLLs and `moonray.exe` also link.
- All 12 upstream common renderer utility tests pass, including aligned storage,
  atomic operations, concurrent ring buffers with exception recovery and atomic
  wait/notification. Simulated nanosecond work in the ring-buffer tests uses a
  measured yield loop on Windows to avoid rounding every delay to a timer tick.
- The initial RATS sphere-scene plugins build, including SphereGeometry,
  RdlMeshGeometry, PerspectiveCamera, DwaSolidDielectricMaterial, ImageMap and
  EnvLight. UsdPreviewSurface also builds and exports its attribute metadata.
- The upstream RATS sphere scene passes its render stage in scalar and vector
  modes, producing beauty/alpha, depth, material and state outputs with no NaN
  or infinite channel values. The resulting image has been visually inspected.
  These are render passes, not comparisons against trusted external canonicals.
  Missing-scene and unwritable-output errors return cleanly with exit code 1.
- Twenty render checks pass across ten upstream scenes in scalar and vector
  modes: sphere geometry, camera deltas, camera motion blur, three pixel filters,
  texture gamma on/off, depth of field and material-property outputs.
- Thirty-eight additional checks pass across nineteen scenes in both modes,
  covering baking, curves, points, subdivision creases, USD instances, VDB geometry,
  deep output, combined/textured lights, shadow controls, projected textures,
  coordinate transforms, render windows, multipart EXRs, Cryptomatte, instanced
  volumes, homogeneous scattering and VDB emission. The vector VDB fix replaces
  ISPC aggregate return values with explicit output parameters at the MSVC ABI
  boundary. Multipart output preserves the requested layer names, channel names
  and compression; its layers and the vector VDB result have no NaN/Inf pixels.
- All configured DSOs in MoonRay, Moonshine and Moonshine USD build successfully
  (176 full plugin DLLs staged in the current native build, plus their proxies).
- All configured native targets now build, including the main Arras plugin,
  command-line utilities and upstream test executables. A complete validation run
  passes all 30 native unit suites: 863 upstream CppUnit checks and seven Windows regression
  suites. These include the full PBR, render-driver, SIMD, framebuffer, allocation,
  geometry, ray-tracing and ISPC shading tests. The Windows framebuffer dump test
  checks six format/orientation combinations across processes.
  `build/windows-native-unit-validation-results.json` records the latest result
  and supporting log for each suite. The complete run is recorded in
  `build/windows-native-arras-unit-tests.log` and
  `build/windows-native-arras-unit-detail.log`.
- `hd_render`, `hd_usd2rdl`, the direct `hd_moonray_debug` backend, USD adapters
  and MoonRay shader-discovery/parser plugins build. The RATS skinned-geometry
  scene renders a 256x192 RGBA EXR without NaN or infinite values and exits cleanly.
  Focused tests verify 64-bit Hydra attribute conversion and repeated/overlapping
  delegate lifetimes. The last Windows delegate releases the global driver before
  DLL shutdown, allowing its worker threads to stop normally.
- The C++ vector shading entry point initializes BSDF builders through an exported
  ISPC C ABI wrapper, avoiding MSVC's incompatible convention for the internal
  ISPC vector mask. Shading fixtures use the current API and initialize their
  material extensions. File tests use native path-list separators and verify
  Windows rooted and drive-relative paths without weakening their assertions.
- Installation to `build/windows/install-validation` succeeds. Ten upstream
  RATS render checks pass from that installation with build-tree paths removed
  from the runtime environment; all 32 output image parts have finite numeric
  samples (packed deep subpixel masks are not interpreted as numbers).
  The installed Hydra backend, adapters, shader discovery and parser plugins load,
  and shader definitions for DwaBaseMaterial, UsdPreviewSurface and ImageMap parse.
  The installed Python scene binding creates and edits a SceneContext. Dependency
  DLLs still come from the pinned dependency directories under `build/`; this is
  not the standalone runtime bundle described below. The bundle includes the
  SDR registration modules, and RGB array properties now preserve their array
  type and defaults, resolving the iridescence_colors warning.
- The shader-registry audit checks all 188 exported classes plus a fixture with
  nonempty arrays and large values: 3,988 attributes spanning all 39 RDL types
  retain their USD types and defaults after authoring and reloading a USD file.
  Boolean defaults are no longer inverted; RGB/RGBA roles, tuple arrays, 64-bit
  integers, doubles and matrices preserve their values. A material authored from
  registry defaults also passes through `hd_usd2rdl` and matches native defaults
  for both boolean states, a float, a color and a color array. Native Hydra tests
  cover Sdr integer-switch arrays and conversion from USD double matrices to
  RDL float matrices, including multiple elements and empty arrays. Evidence:
  `build/windows/sdr-current/results.json`, `build/windows-sdr-current-tests.log`
  and `build/windows-hydra-types-tests.log`.
- All 42 HaTS generation commands complete. With the complete plugin set, the
  curves canonical comparison passes and 41 comparisons fail. Separate diagnostic
  runs of 15 scenes match their checked-in canonicals with `doubleSided=true`.
  The other comparisons depend on unavailable studio assets, the legacy
  BaseMaterial shader, a studio-only procedural adapter, USD prototype naming,
  or exact floating-point equality. See the breakdown below. Generation success
  alone does not prove correct translation. The checked-in canonicals have not
  been changed.
- The USD geometry and instance plugins, orthographic camera, rectangular light,
  DwaBaseMaterial and DwaMetalMaterial build. Their USD reader uses the installed
  USD 23.08 libraries.
- OpenImageIO 2.4.14, OpenSubdiv 3.5, Random123, Python, Boost, Lua and other initial
  dependencies build successfully through the pinned manifest.

The port includes Windows library loading, explicit shared attribute-data imports,
binary-safe Lua generation, fixed-width wire types, matching aligned allocation
and deallocation, native CPU affinity, and MSVC build settings. Process-wide CPU
affinity currently reports an error on machines with multiple processor groups;
individual worker pinning supports processor groups. That multi-group behavior
has not yet been tested on suitable hardware.
Heatmap timing uses Windows thread CPU accounting (`GetThreadTimes`); its sampling
granularity is coarser than the stored nanosecond unit.
CPU/NUMA checks currently cover a machine with 14 logical CPUs, one socket and
one NUMA node. Windows NUMA allocation uses a preferred node, reports available
memory at discovery time, and reports unknown inter-node distances as `-1`.

Windows shared memory and affinity semaphores use files in
`%LOCALAPPDATA%/OpenMoonRay/shared-memory-v1`, protected by the user's SID ACL.
They coordinate processes belonging to that user; cross-user affinity sharing
is not implemented. Unix permission bits remain diagnostic categories on Windows.
Shared memory persists after process exit, including forced termination. Kernel
file locks track up to 4096 simultaneous views per segment and release crashed
processes' leases. Cleanup rechecks leases while holding the registry lock.
The semaphore adapter supports the binary `SEM_UNDO` operations used by the
affinity table, not arbitrary System V semaphore sets.

The native grid suite can be reproduced with:

```powershell
& .\building\windows\Build-MoonRay.ps1 -Targets scenerdl2_common_grid_util_tests
& .\building\windows\Test-SceneRdl2.ps1 -Native -TestRegex '^scenerdl2_common_grid_util_tests$'
```

## Remaining completion gates

1. Complete trusted-reference image comparisons.
2. Resolve reference compatibility for Hydra acceptance testing.

All native unit suites can be run with:

```powershell
& .\building\windows\Build-MoonRay.ps1
. .\building\windows\Enter-BuildEnvironment.ps1
. .\building\windows\Enter-MoonRayEnvironment.ps1
ctest --test-dir build/windows/native -L '^unit$' --output-on-failure -j2 --timeout 600
```

The installation can be checked separately from build-tree DLLs and plugin
metadata. It currently uses the pinned dependency installations under `build/`:

```powershell
cmake --install build/windows/native --prefix "$PWD/build/windows/install-validation"
. .\building\windows\Enter-MoonRayEnvironment.ps1 -InstallPrefix .\build\windows\install-validation
& "$env:PYTHONHOME/python.exe" .\building\windows\tests\test_installed_renders.py .\build\windows\install-validation
```

The installed-render check executes fourteen unchanged upstream RATS commands for
sphere geometry, VDB geometry, multipart output and deep Cornell-box output in
both execution modes, plus Op/Ramp display filters, vector glitter and Hydra skinned geometry. It checks
every resulting image part for finite numeric samples; deep subpixel-mask
channels are packed bit patterns and are excluded from numeric finiteness checks.
The display-filter checks also verify unit-length RGB or black after normalization
and the expected color at the radial ramp's center.
It writes `build/windows/installed-rats-output/results.json`. It does not compare
images to trusted canonicals or replace reference files.

The Arras integration check can also use a remote coordinator. Load the runtime
environment first, then supply the coordinator's base URL and session definitions
for the worker platform:

```powershell
& "$env:PYTHONHOME/python.exe" building/windows/tests/test_arras_renders.py `
  build/windows/moonray-runtime `
  --remote-url 'http://render-coordinator:8087' `
  --session-directory 'D:\render-config\linux-sessions' --timeout 600
```

The remote definitions must contain `hd_single.sessiondef` and
`hd_multi.sessiondef`. Their computation library names, packaging environment,
and resource requirements must match the workers. The bundled definitions name
Windows DLLs; Linux workers need their Linux definitions, such as
`libcomputation_progmcrt.so`. The test uses one remote worker and checks scalar
and vector rendering, a geometry update, finite nonempty RGBA images, and evidence
of session creation and a TCP connection. Results are written separately to
`build/windows/remote-arras-output/results.json`. For a local installed-worker
check, omit the remote options and use `--bundle` when testing the standalone
runtime.

The remote check passes with the v6 Windows bundle and the published MoonRay
2.40 Linux package (Snap revision 12) in Ubuntu 24.04. It uses the real
`arras4_node`, `arras4_router`, and `execComp` with the repository's unmodified
minicoord service. A loopback NAT relay translates the coordinator's returned
worker address; rendering data travels through QEMU's TCP forwarding unchanged.
Both execution modes produced an initial image and a changed geometry-update
image, all finite RGBA at 256 by 192. Linux logs corroborate each session's
`libcomputation_progmcrt.so` load, and the coordinator reports zero sessions
afterward. Evidence is in `build/windows-remote-arras-tests.log`,
`build/windows/remote-arras-output/results.json`, and
`build/linux-reference/remote-arras-stable-validation.json`. This is an
interoperability check: the older worker warns about newer scene attributes,
and these images have not been accepted as canonical references.

## Standalone Windows runtime

After installing the native renderer with Arras enabled, build a new runtime
directory and validate it without Visual Studio or checkout DLLs in `PATH`:

```powershell
& .\building\windows\Package-MoonRay.ps1 -OutputDirectory 'build/windows/moonray-runtime'
& .\building\windows\Test-RuntimeBundle.ps1 -BundleDirectory 'build/windows/moonray-runtime'
. .\build\windows\moonray-runtime\Setup.ps1
hd_render -renderer Moonray -in scene.usd -out scene.exr
```

`Package-MoonRay.ps1` refuses to overwrite an existing directory. It copies the
renderer, native Arras worker, USD plugin resources, Python 3.11, CPU OIDN, MSVC
redistributable DLLs and their runtime dependencies. CMake scans the PE imports;
missing dependencies and conflicting DLLs fail packaging. Component notices are
retained under `licenses/`, and `manifest.json` records each file's source and
SHA-256 hash. The bundle is a CPU runtime; development headers, GPU backends,
and DCC applications are not included. Use `Setup.cmd` from Command Prompt.

The current bundle contains 3,515 manifest-verified files (about 566 MiB before
compression). Validation on Windows 11 build 26200 passes from a relocated path
containing both spaces and `é`, with only bundle/Windows paths configured. It
checks scene and USD ASCII/binary round-trips, Hydra/plugin-resource discovery,
all 188 shader/class definitions plus a typed-value fixture, material translation,
fourteen upstream direct-render cases (66 parts with finite numeric samples),
and scalar/vector Arras rendering with geometry updates (four finite RGBA images).
An audit of the Python process verifies that all 139 loaded modules come from
the bundle or Windows. This is a restricted-environment test on the development
machine; a separate clean Windows VM has not been tested.

Evidence: `build/windows-runtime-v7-tests.log`,
`build/windows/bundle-validation/results.json`, and
`build/windows/bundle-validation/loaded-modules.json`.
The verified archive is `build/windows/moonray-windows-x64.zip` (about 298 MiB),
with its SHA-256 in the adjacent `.zip.sha256` file. Every archived file was
checked against the manifest; see `build/windows-runtime-archive-validation.json`.

The Unicode checks exercise native UTF-16 environment access, UTF-8 filesystem
paths and session-definition loading. `Patch-USD.py` also corrects the pinned
USD 23.08 environment, DLL-path and `plugInfo.json` handling. The bundle includes
the upstream Python registration modules for the two SDR plugins, alongside the
USD Python package. Shader-registry validation is part of the bundle check;
`build/windows/bundle-validation/shader-registry-results.json` records every class
and attribute type checked. Run the audit separately with the selected runtime
environment already loaded:

```powershell
& "$env:PYTHONHOME/python.exe" building/windows/tests/test_shader_registry.py `
  --definitions build/windows/install-validation/coredata `
  --report build/windows/shader-registry-results.json `
  --translator build/windows/install-validation/bin/hd_usd2rdl.exe
```

The source changes span the `cmake_modules`, `scene_rdl2`, `moonray`, `moonshine`, `moonshine_usd`,
`mcrt_denoise`, `arras/arras4_core`, `moonray/moonray_arras/mcrt_messages`,
`moonray/moonray_arras/mcrt_dataio`, `moonray/moonray_arras/mcrt_computation`,
`rats`, `moonray/hydra/hdMoonray`, and
`moonray/hydra/moonray_sdr_plugins` submodules. Preserve their working tree changes together
with this directory when transferring the in-progress port.

## Upstream render and reference tests

The renderer also contains five legacy PPM images under
`moonray/moonray/tests/lib/rendering/shading/ispc/ref/macos/`. This revision no
longer contains the `TestRender` fixture that produced/compared those files.
They are not the external RATS EXR reference set; the active ISPC shading suite
performs numeric assertions.

The native configuration includes the repository's `rats/` Render Acceptance Test
Suite. Bootstrap installs OpenImageIO's `idiff`, `oiiotool` and Python bindings.
Fetch the RATS scene assets with Git LFS before rendering:

```powershell
git -C rats lfs install --local
git -C rats lfs pull
& .\building\windows\Build-MoonRay.ps1 -ConfigureOnly
& .\building\windows\Test-Rats.ps1 -List
& .\building\windows\Test-Rats.ps1 -Stage Render -Mode scalar
& .\building\windows\Test-Rats.ps1 -Stage Render -Mode vector
& .\building\windows\Test-Rats.ps1 -CanonicalDirectory 'D:\reference\rats_canonicals'
```

The default selection is `moonray/geometry/sphere`; use `-TestRegex` to select
other tests, `-Threads` to control renderer threads, and `-TimeoutSeconds` for
longer renders. Each test retains its upstream scene, image dimensions, sampling
settings, output channels and comparison thresholds. Outputs are under
`build/windows/native/rats/tests/`, with CTest logs under `Testing/Temporary/`.

The current v7 CPU/default run selected 650 tests: 645 passed and five disabled
upstream. It completed 106 enabled cases before the user-requested pause and
539 after resuming. `build/windows-rats-v7-validation-results.json` records
each result, and `build/windows-rats-v7-combined-results.xml` combines the two
batches. The interrupted batch's results were recovered from its original CTest
log; the resumed batch has CTest-generated JUnit. Image freshness was checked
against each batch's own start time before combining the audits.

Earlier fixes preserve small area-scaled
geometric normals in deep output and reserve a 16 MiB stack for `moonray`,
`hd_render` and `execComp` on MSVC. All ten stack-overflow failures and both deep
Cornell-box modes pass their reruns; the PBR unit suite also passes.
OpDisplayFilter now leaves black pixels black when normalizing. Both float and
color ISPC radial-ramp evaluators avoid `atan2(0, 0)` at the center. All six
affected upstream render cases and both shading unit suites pass. Pixel checks
confirm the formerly NaN samples have the expected colors; see
`build/windows-displayfilter-pixel-check.json`. The installed-render check covers
both display filters in scalar and vector modes.

`tests/check_rats_outputs.py` audits declared images plus newly written EXRs for
readability, freshness and non-finite numeric samples. Its `--manifest` input is
the JSON from `ctest --show-only=json-v1` with the matching `rats`, `update` and
execution-mode labels; it reads declared filenames without executing any update
command. Pass the render JUnit XML with `--junit` and an output JSON with `--report`.
The current audit covers 992 files and 996 image parts, with no numeric NaNs.
Its strict finite-only policy still flags ten files and exits nonzero. Eight
use min/max/closest filters, whose empty-sample values are explicitly signed
infinities (`AovSchema::Entry::defaultValue`); the signs match their filters.
The other two are the reflected/refracted Cryptomatte scene's dummy
`throwaway.exr`: its float32 primitive IDs overflow the default half channels.
Isolated diagnostic renders changing only that output to float32 are entirely
finite, and converting them to half exactly reproduces both original outputs,
including all 5,035 infinities per mode. Upstream scenes and references remain
unchanged. The diagnoses were repeated against v7's outputs. Evidence:
`build/windows-rats-v7-output-check.json` and
`build/windows/aov-infinity-diagnostics-v7/results.json`. The deep Cornell-box
numeric channels pass; only their packed subpixel masks are excluded.

RATS canonical EXRs and `diff.json` tolerances are external to this checkout.
Its README requires a trusted renderer to generate them; its macOS CI uses
`/Applications/MoonRay/rats_canonicals`. A render-only pass does not establish
image parity with a trusted build. The Windows helper never updates canonicals.

A public-reference search on October 12 found no downloadable trusted RATS
canonical set in upstream releases, public CI artifacts, the six public RATS
forks' default branches/releases, or documentation downloads. The
[upstream README](https://github.com/OpenMoonRay/rats#rats-ctest-suite) describes
generating images and `diff.json` from 25 trusted-build renders, and notes that
different hardware/OS classes may require their own references. The
[public scene downloads](https://docs.openmoonray.org/getting-started/test-scenes/)
provide scene inputs, not the RATS canonical outputs. Search evidence is retained
in `build/linux-reference/public-canonical-search/`; unindexed or private sets
were not ruled out.

An independent hosted Linux reference job is available under
[`reference/`](reference/README.md), with a workflow at
`.github/workflows/windows-port-reference.yml`. It verifies and extracts the
published Linux package without changing Windows features, then uses the
existing 25-candidate RATS updater. It supports a five-case initial run and
all 645 enabled CPU/default cases in 16 shards. The local setup and test-selection
checks pass in the existing Linux VM. With user approval, the job was published
to `ThomasBignolas/openmoonray`, branch `codex/windows-reference-validation`, on
October 12. The first hosted attempt verified the published package and runtime
but could not find the runner's CMake after isolating the renderer environment.
The runner now resolves absolute CMake/CTest paths before changing that environment.
The corrected [focused run](https://github.com/ThomasBignolas/openmoonray/actions/runs/38261688406)
passed all five 25-candidate updates and produced eleven canonical images.
Seven of the eleven Windows comparisons pass the unchanged Linux-derived
tolerances: Hydra skinned geometry, scalar sphere beauty/material,
and all four vector sphere outputs. Scalar sphere
depth/state and scalar/vector checkerboard fail. The scalar checkerboard differs
at three of 65,536 pixels, maximum error 0.0078125; sphere depth/state maximum
error is 0.03125. These failures remain unresolved. Fresh renders from the
unchanged v8 package and preserved outputs give the same pass/fail outcomes.
All 860 scene/asset input files match, allowing only Git's CRLF checkout conversion
for 767 text files. The [full-suite run](https://github.com/ThomasBignolas/openmoonray/actions/runs/38263010850)
is generating all 645 references in 16 shards, at most four concurrently.
The downloaded reference artifact, input hashes, unchanged thresholds, comparison
logs and repeat evidence are retained under `build/windows/hosted-reference/`;
`focused-results.json` records the current acceptance gap.

The Linux images generated under the original Windows QEMU 11.1.0 executable
are diagnostic evidence only. An exact rational-arithmetic check found incorrect
rounding for two of ten binary32 fused multiply-add inputs captured from the
sphere transform calculation. Linux `std::fma`, the FMA instruction intrinsic and
an indirect `fmaf` call all reproduce the errors under this emulator with
round-to-nearest active. Native Windows gives the correct results for all ten
inputs through all three paths. Consequently, those emulated Linux images cannot
establish strict image acceptance or justify changes to Windows arithmetic.
The original images and comparison failures are preserved. Evidence:
`build/linux-reference/fma-environment-validation.json` and
`sphere-transform-comparison.json`. A separately staged MSYS2 UCRT QEMU 11.1.2
passes all 2,048 deterministic FMA inputs through all three paths against exact
arithmetic, as does native Windows. The standalone sphere inverse calculation
also matches Windows with FMA contraction enabled. Package checksums, inputs,
FP modes and results are recorded in `build/linux-reference/ucrt-math-validation.json`.
The focused rerender of pixel `(179,74)` now matches Windows exactly for the
half-float beauty, depth, material and state outputs. Full-float beauty maximum
error at that pixel falls from `0.0144674` to `1.78814e-7`; both platforms now
select the near sphere intersection for the previously divergent sample.
See `build/linux-reference/ucrt-sphere-pixel-comparison.json`. This is a single
pixel diagnostic, not full-image acceptance. An additional full sphere rerun was
cancelled after 490 seconds once its earlier 30-minute emulated runtime was
reviewed; the replacement emulator is slower. The cancelled case remains a
failure in the original JUnit report and its outputs are excluded from comparisons.

The first complete UCRT reference, Hydra `geometry/skel`, renders successfully
and has finite pixels with the same image layout. Its strict `1e-6` comparison
still fails: mean/RMS/max error are `4.77379e-6` / `6.87027e-5` / `0.00339425`,
with 1,117 of 49,152 pixels exceeding the threshold. A repeat of the unchanged
Windows render has mean/RMS/max error `1.97091e-6` / `5.58329e-5` / `0.00360894`
against the first Windows result, with 138 pixels exceeding the threshold.
This demonstrates render variability but does not explain every cross-platform
difference or establish statistical acceptance. Evidence:
`build/linux-reference/ucrt-hydra-first-comparison.json` and
`ucrt-hydra-windows-repeat-comparison.json`.

Both complete UCRT checkerboard renders also succeed. Scalar and vector each
differ from Windows at the same 13 of 65,536 pixels, with maximum RGB error
`0.015625` and identical alpha. Within either platform, the scalar/vector maximum
error remains `4.76837e-7`. All three completed references have matching layouts
and finite numeric samples. The actual RATS diff tests still report zero passes
and three failures at the unchanged strict defaults; candidate/reference hashes
are unchanged after comparison. No statistical tolerances were generated.
The original four-case render JUnit retains the intentionally cancelled sphere
case alongside the three successful renders. Evidence:
`build/linux-reference/ucrt-selected-reference-comparison.json`,
`ucrt-selected-reference-acceptance.json`, `ucrt-selected-reference-diff-results.xml`,
`ucrt-checkerboard-difference-diagnosis.json`, and the collected
`ucrt-selected-references/render-summary.json`.

A passive trace at checkerboard pixel `(85,117)` reproduces both full renders
exactly and identifies one differing colour decision among 64 samples. At sample
42, the scaled V coordinate is `0.9999998807907104` on Linux and
`1.0000004768371582` on Windows. Both `fmodf` results agree with exact remainders;
the discontinuity is crossed by a six-ULP input-coordinate difference before the
shader chooses its colour. This explains that pixel, not all 13 discrepancies.
See `build/linux-reference/checker-boundary-trace-comparison.json`.

Separate diagnostic DLLs initially tested `/fp:contract` against the v7 binaries.
Recompiling the three camera files reduces the strict checkerboard
pixel count from 13 to 12 but slightly increases RMS error; recompiling `Box.cc`
gives eight differing pixels, and combining both gives seven. The baseline probe
reproduces the full Windows image exactly. Evidence:
`build/linux-reference/checker-arithmetic-probe-comparison.json`.

Subsequent passive Box traces locate two sources of rounding differences: the
inverse transform computed by `geom/Box.cc` through `Box::setTransform`, and the
intersection arithmetic in `geom/prim/Box.cc`. The incoming ray and hit distance
agree exactly at sample 42. Compiling both files with contraction naturally
reproduces the Linux inverse matrix, UV and critical pixel without replayed data.
The complete checkerboard then differs at six pixels; including the camera
change reduces this to five, with maximum error `0.0078125`. The isolated probes
are recorded in `box-primary-trace-comparison.json`,
`box-matrix-replay-comparison.json`, `box-natural-contraction-verification.json`,
and `camera-camera-box-transform-contract-checkerboard-comparison.json` under
`build/linux-reference/`.

The current source enables `/fp:contract` in the MSVC options for the renderer,
scene math, shader plugins and Hydra. It retains MSVC's default precise math
policy while permitting fused multiply-add, which the GCC AVX2 build already
uses. Visual Studio 2022 otherwise disables contraction by default; see
[Microsoft's floating-point option reference](https://learn.microsoft.com/en-us/cpp/build/reference/fp-specify-floating-point-behavior?view=msvc-170)
and [GCC's contraction option](https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html#index-ffp-contract).
The complete candidate builds successfully and reproduces the five-pixel result
in both scalar and vector modes. Hydra's reference comparison has mean error
`3.88577e-6`, RMS `6.86094e-5`, maximum `0.00431663`, and 804 failing pixels;
its maximum error is larger than v7 despite a lower mean error. All three real
RATS diff cases still fail their unchanged defaults, with input hashes verified.

All 31 native unit/integration suites pass after two follow-ups. The thread-pool
watchdog failed during concurrent suite execution and passed when rerun alone.
The primitive attribute test needed the existing out-of-line expected-transform
helper extended to vectors; exact equality remains required, and the no-inline
attribute now also works on MSVC. The original failures and subsequent passes
are preserved under `build/windows/fp-contract-validation/`.

The separate `MoonRay Windows é v8` runtime passes relocation validation: 3515
manifest files, 139 loaded modules confined to the bundle and Windows, 189 shader
classes / 3988 attributes, 14 direct renders, and scalar/vector Arras rendering
with geometry updates. Its full rerun passed all 645 enabled render cases in
943.92 seconds; five remain disabled upstream. The audit covers 992 renderer
outputs / 996 parts, plus three existing comparison images. It finds zero
numeric NaNs and the same ten diagnosed infinity cases, channels and counts as
v7. The strict output audit therefore still records ten errors. The v7 package
and its image/test evidence remain preserved. Current candidate reports
are in `build/windows/fp-contract-validation/`, including
`selected-reference-comparison.json`, `diff-summary.json`, and
`runtime-results.json`, and `validation-summary.json`. The full-run wrapper's
initial summary assertion missed disabled entries without a `skipped` element;
the corrected summary was recovered from the original 650-entry JUnit and CTest
log without repeating renders. The focused Hydra scene-translation recheck still has
four matrix differences no larger than `8.881784197001252e-16`.

The five remaining v8 checkerboard pixels have now been traced separately.
Passive traces preserve the full-render values and show identical raster samples,
camera matrices and Box transforms. An actual-header math probe reproduces all
320 camera rays on each platform. Exchanging only the approximate reciprocal-
square-root starting value reproduces the other platform's rays exactly in both
directions; both unchanged-value controls also pass. Replaying the critical Linux
ray in an isolated Windows Box DLL reproduces four of the five Linux pixels
exactly, with all other hits unchanged.

The fifth pixel, `(233,145)`, has an identical incoming ray. MSVC and the published
GCC build fuse different products in the Box transform, producing a one-ULP
difference in its local Z direction. Exact rational rounding reproduces both
results. Using the published operation grouping in an isolated diagnostic also
reproduces this pixel's Linux texture coordinate and final colour exactly.
These findings explain the five scalar checker differences; they do not establish
full-image acceptance, account for every Hydra difference, or justify changing
the packaged renderer to imitate the emulator. No production arithmetic or
comparison tolerance was changed by these diagnostics. Evidence:
`build/linux-reference/camera-all-mismatch-traces.json`,
`camera-all-seed-replay-comparison.json`, `box-all-ray-replays/results.json`, and
`box-233-dot-rounding-comparison.json`. The ray-only report retains its fifth-pixel
failure; the separate operation-grouping report resolves that diagnosis.

The image-comparison harness has separately passed synthetic checks for identical
images, accepted tolerance, excessive differences, missing tools and missing
results (`tests/test_rats_diff.py`); those fixtures are not render references.
The canonical updater also passes a synthetic 25-candidate round trip in both
Hydra's `default` mode and scalar mode (`tests/test_rats_canonical_roundtrip.py`).
It preserves the mode's directory and JSON key, passes thread options only to
direct MoonRay commands, and scores each candidate against every other candidate.
The check verifies selection of the lowest-error candidate and confirms that
generated tolerances accept an identical image and reject an incorrect one.

An independent scalar sphere render from the published Linux Snap revision 23
exposed a Windows sampling difference: the light-name seed used `std::hash`, whose
MSVC and libstdc++ results differ. Windows now uses the existing Linux hash
sequence for lights; other platforms retain their previous behavior. The
`windows_light_sampling_hash` unit test checks 36 values captured independently
from the Linux standard library, including high-bit bytes, embedded NULs and all
tail lengths. The PBR unit suite passes after the fix.

Against that unchanged Linux image, the scalar sphere's mean beauty error falls
from `0.00586644` to `0.00000246437`. One pixel accounts for about 85% of the
remaining squared color error and also has a differing geometric depth. The
strict `1e-6` comparisons still fail; these measurements do not substitute for
RATS's generated reference tolerances. All five image outputs and every image
part were checked. Evidence is in
`build/linux-reference/sphere-edge-hashfix-comparison.json` and
`build/linux-reference/sphere-hashfix-residual.json`.
The matching Linux vector sphere run also completed. Against the updated v7
package, its mean beauty error is `0.000143463` and maximum error is `0.00541615`;
strict comparisons still fail. See
`build/linux-reference/sphere-edge-vector-v7-comparison.json`.

Repeated vector renders from the same Windows v7 bundle also vary: their mean
beauty difference is `0.000139799`, RMS `0.000361674`, and maximum `0.00573093`.
That is similar to the Linux/Windows vector difference, so the strict comparison
alone does not isolate a platform defect. This does not establish acceptance or
replace Linux-generated statistical tolerances. See
`build/linux-reference/sphere-vector-v7-bundle-repeat-comparison.json`.
An independent instruction probe also found that the emulated Linux CPU and
physical Windows CPU produce different approximate reciprocal/reciprocal-square-
root results for 512/511 of 512 identical inputs; exact division and square root
agree for all inputs. `build/linux-reference/approx-math-comparison.json` records
the values. This is a measured test-environment difference, not proof that it
causes a particular image mismatch.
The largest scalar mismatch now reproduces in a 49-pixel viewport; those samples
match each platform's full render exactly. This permits focused diagnosis without
another full Linux render (`build/linux-reference/sphere-scalar-crop-diagnosis.json`).
Tracing its 64 primary rays locates one ray within two float ULPs of the sphere's
phi clipping boundary. In an isolated diagnostic DLL, selecting the far root for
only that ray reproduces Linux's half-float beauty, depth, material and state
values exactly; the float beauty error falls from `0.0144674` to `0.00000639260`.
This localizes the large pixel difference to the clipping decision. It does not
identify which preceding arithmetic operation moves the Linux ray across the
boundary. The diagnostic DLL is excluded from the bundle, and the production
sphere code remains unchanged. See
`build/linux-reference/sphere-boundary-probe-results.json`.

An independent pass-through Embree callback trace from the published Linux
renderer confirms that this ray takes the far root on Linux and the near root
on Windows. Its incoming world-space Z direction differs by one float ULP.
Replaying the exact Linux direction in an isolated Windows diagnostic still
selects the near root, so the incoming-ray difference alone does not explain
the clipping decision; subsequent transform or intersection arithmetic also
needs investigation. Both tracing runs reproduce their original output pixels.
See `build/linux-reference/sphere-cross-platform-ray-trace.json` and
`build/linux-reference/sphere-linux-ray-replay-results.json`. These diagnostic
DLLs are excluded from the runtime package.
Compiling only the isolated sphere object with MSVC `/fp:contract`, both with
the original input ray and with the captured Linux ray, still selects the near
root. Neither probe fixes the differing pixel; production compiler options are
unchanged (`build/linux-reference/sphere-fp-contract-probe-results.json`).

Three more full Linux reference renders completed with the upstream settings:
the Hydra skinned-geometry scene and the checkerboard shader in scalar and vector
modes. All three real RATS diff cases fail the default `1e-6` threshold; no
`diff.json` was generated and no thresholds were changed.

| Reference case | Mean absolute error | Maximum error | Pixels above `1e-6` |
| --- | ---: | ---: | ---: |
| Hydra skinned geometry | `5.63644e-6` | `0.00836684` | 1,338 / 49,152 |
| Scalar checkerboard | `1.62721e-6` | `0.015625` | 16 / 65,536 |
| Vector checkerboard | `1.62750e-6` | `0.015625` | 16 / 65,536 |

The checkerboard differs at the same 16 positions in both modes, with identical
alpha. Within either platform, scalar/vector maximum error is `4.76837e-7` and
no pixels exceed `1e-6`. This narrows the remaining difference but does not prove
its cause or establish image acceptance. All three image layouts match and their
numeric samples are finite. Original candidate/reference hashes are unchanged
after RATS comparison. Evidence: `build/linux-reference/selected-reference-comparison.json`,
`selected-reference-acceptance.json`, `selected-reference-diff-results.xml`, and
`checkerboard-difference-diagnosis.json` in that same directory.

hdMoonray's `hats/` directory does include 42 canonical RDLA scenes for comparing
USD-to-RDL translation. Run the existing tests from the native build:

```powershell
& .\building\windows\Build-MoonRay.ps1 -Targets hd_moonray_debug,hdMoonrayAdapters,hd_render,hd_usd2rdl,rdl2_compare,moonrayShaderDiscovery,moonrayShaderParser,AttributeMap
. .\building\windows\Enter-BuildEnvironment.ps1
. .\building\windows\Enter-MoonRayEnvironment.ps1
hd_render -renderer
$env:RATS_HD_RENDERER = 'Moonray (debug)'
& .\building\windows\Test-Rats.ps1 -Stage Render -Mode default -TestRegex 'hd_render/geometry/skel$'
ctest --test-dir build/windows/native -R '^hats_(generate|compare)_' --output-on-failure -j2
```

The HaTS `copy` stage replaces reference files and is not part of validation.
The current unmodified suite reports 42 successful generation commands and
1 successful comparison out of 42 (`build/windows-hats-current-results.xml`).
Diagnostics in `build/windows/hats-diagnostics/results.json` account for the
remaining comparisons:

| Count | Difference from the checked-in canonical |
| ---: | --- |
| 16 | Canonical requires the absent legacy `BaseMaterial` shader. |
| 15 | Only geometry sidedness differs; all 15 match exactly when generated with `-set doubleSided true`. The upstream default tests still fail. |
| 7 | Input USD references unavailable `/work/...` studio textures, geometry payloads or VDB files. Some also have sidedness differences. |
| 1 | `geometry_procedural` needs the studio `Procedural` schema/adapter; its source is enabled only by `STUDIO=GLD`. |
| 1 | `geometry_instances` has different USD prototype paths, the Cryptomatte IDs derived from those names, and sidedness. |
| 1 | `geometry_skel` has matrix differences no larger than `8.89e-16`; `rdl2_compare` uses exact equality. Replacing only those matrices in a separate diagnostic copy makes the comparison pass. |

These diagnostics do not change comparison tolerances, renderer defaults or the
42 canonical files; reference hashes were checked before and after the probes.

An independent Linux comparison now corroborates the translation behavior. The
published Linux Snap revision 23 (`v2026.29.1-80-g336a89c`) and the Windows bundle
generated all 42 scenes afresh. Forty-one pairs compare exactly with
`rdl2_compare`. The sole remaining pair, `geometry_skel`, differs only in four
transform matrices, by at most `8.881784197001252e-16`; a separate diagnostic copy
with just those matrices replaced compares exactly. The renderer, shader, Hydra,
Arras and RATS component revisions match. Two differing component revisions
change only Python-module CMake layout and FindTBB's minimum CMake version.
See `build/linux-reference/reference-provenance.json`,
`build/linux-reference/hats-comparison/results.json`, and
`build/linux-reference/hats-comparison/roundoff-diagnosis.json`.
Rechecking `geometry_skel` under the FMA-validated UCRT emulator retains the same
four matrix-only differences and the same `8.881784197001252e-16` maximum error
(`build/linux-reference/ucrt-hats-skel-comparison.json`).
This establishes parity for the scene data that both builds translate. It does
not restore unavailable studio assets or make the older checked-in comparisons
pass; all 42 original reference hashes remain unchanged.

`HDMOONRAY_BUILD_ARRAS_PLUGIN` defaults to OFF in the Windows native entry point;
the upstream hdMoonray project retains its default ON. The direct backend uses
the real renderer. The Arras backend builds with the optional procedure below
and supports native local sessions. A Windows client also passes scalar/vector
rendering and interactive geometry updates with the Linux worker described above.
`Build-USD.ps1` applies a narrow export fix to the pinned USD 23.08 source so that
external light adapters can link to `UsdImagingLightAdapter` on Windows.
Bootstrap also patches OpenImageIO 2.4.14 to honor IOProxy for multipart/deep EXRs.
This lets the renderer retain Windows delete-on-close temporary files while
writing multipart output. The ordinary filename writer is unchanged.

## Arras client and main hdMoonray plugin

Install the manifest dependencies, then build the Arras client stack before
enabling the main plugin:

```powershell
& .\building\windows\Build-Arras.ps1
& .\building\windows\Build-MoonRay.ps1 -WithArras
. .\building\windows\Enter-BuildEnvironment.ps1
. .\building\windows\Enter-MoonRayEnvironment.ps1
ctest --test-dir build/windows/arras --output-on-failure
ctest --test-dir build/windows/native -R '^(windows_mcrt_|windows_hydra_arras_lifecycle|mcrt_dataio_)' --output-on-failure
```

Arras installs under `build/deps-arras`, including `bin/execComp.exe` and
`computation_impl.dll`. Twenty-eight Arras suites cover TCP binary data,
disconnect/refusal handling, filesystem IPC, HTTP GET/POST, SDK/session-file
lifecycle and the worker process. Worker checks load a computation DLL from a
path with spaces and non-ASCII characters, validate registration and routing,
exchange binary messages with and without wire chunking, check heartbeat data,
and verify callbacks, normal shutdown and error exits. They cover missing DLLs,
missing factories, rejected initialization, startup exceptions, disconnects and
stops before startup. Additional socket checks cancel blocked reads and writes;
the shutdown cases pass ten consecutive runs.

Six process-manager tests check native argument quoting, Unicode environment and
working directories, explicit handle inheritance, CPU/memory job limits, large
stdout/stderr capture, child-tree cleanup, controlled termination, process reuse
and manager shutdown. Seven local SDK tests check real worker startup, chunked
binary replies, repeated sessions, disconnect cleanup, early initialization
failures, Unicode temporary paths and asynchronous sending. The async case also
checks the `"*"` routing filter used by hdMoonray's session definition.

All twenty-eight also pass in an independent consumer using installed headers,
libraries and `execComp`, without the Arras source build in its runtime path.
Six additional native suites cover main-plugin delegate lifetimes,
MoonRay TCP/IPC, CPU/memory/network telemetry, RDL binary message serialization and
the upstream merger/value-tracker tests. Evidence is in
`build/windows-arras-local-final-tests.log`,
`build/windows-arras-routing-tests.log`,
`build/windows-arras-worker-shutdown-repeat-tests.log`,
`build/windows-arras-local-consumer-tests.log` and
`build/windows-native-computation-dependencies-tests.log`.
The installed main plugin also passes its delegate lifecycle test with build-tree
runtime paths removed (`build/windows-installed-arras-lifecycle.log`). All seven
installed direct-render RATS checks still pass after the Arras integration
(`build/windows-installed-arras-rats-validation.log`).

To reproduce the independent installed-package checks:

```powershell
. .\building\windows\Enter-BuildEnvironment.ps1
cmake -S building/windows/arras-install-check -B build/windows/arras-worker-install-check -G Ninja `
    -DCMAKE_BUILD_TYPE=Release "-DARRAS_INSTALL_PREFIX=$PWD/build/deps-arras" `
    "-DCMAKE_TOOLCHAIN_FILE=$PWD/build/tools/vcpkg/scripts/buildsystems/vcpkg.cmake" `
    "-DVCPKG_INSTALLED_DIR=$PWD/build/deps" -DVCPKG_MANIFEST_MODE=OFF
cmake --build build/windows/arras-worker-install-check --parallel 8
ctest --test-dir build/windows/arras-worker-install-check --output-on-failure
```

Windows socket handles retain their full width. IPC uses Windows AF_UNIX with
filesystem endpoints; Linux abstract socket names are unsupported. Session search
paths use semicolons so drive letters and spaces work. Telemetry uses Windows
performance counters and IP Helper APIs. `Enter-MoonRayEnvironment.ps1` selects
the generated or installed session definitions through `ARRAS_SESSION_PATH`.

The native computation, merge and dispatch DLLs all build. The main `Moonray`
Hydra backend renders the upstream skinned-geometry scene through `arras:local`.
From the installation, scalar and vector modes each pass an initial render and
a geometry-rotation update in the same session. All four 256x192 RGBA outputs
contain visible content and finite pixels; the update measurably changes the
image. These tests check actual progressive-frame traffic from
`computation_progmcrt.dll`, with build-tree runtime paths excluded:

```powershell
cmake --install build/windows/native --prefix "$PWD/build/windows/install-validation"
. .\building\windows\Enter-MoonRayEnvironment.ps1 -InstallPrefix .\build\windows\install-validation
& "$env:PYTHONHOME/python.exe" building/windows/tests/test_arras_renders.py build/windows/install-validation
```

Results are recorded in `build/windows-installed-arras-render-tests.log` and
`build/windows/installed-arras-output/results.json`. This does not establish
parity with external trusted canonical images.

Local Windows sessions support current-environment packaging. Bash/Rez packaging,
process pause/resume, Linux cgroups/memory loans and the optional `/proc`-based
RecLoad diagnostic logger are unsupported; native SysUsage telemetry works.
`allowCoreDump` is a POSIX setting; Windows crash dumps use Windows Error Reporting.
Remote Linux rendering passes with the Linux worker's session definitions as
described above. Generated Windows templates use Windows library suffixes;
configure `ARRAS_SESSION_PATH` with the destination worker's definitions when
connecting to Linux workers.
`-WithArras` persists
in the CMake cache; disable it explicitly with
`cmake -S building/windows/native -B build/windows/native -DHDMOONRAY_BUILD_ARRAS_PLUGIN=OFF`.
