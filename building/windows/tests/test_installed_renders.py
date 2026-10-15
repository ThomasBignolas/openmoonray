"""Run upstream RATS commands against installed binaries and check finite pixels.

This checks installation and rendering, not parity against trusted canonicals.
Dot-source Enter-MoonRayEnvironment.ps1 -InstallPrefix before invoking it.
"""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("install", type=Path)
args = parser.parse_args()
install = args.install.resolve()
repo = Path(__file__).resolve().parents[3]
native = repo / "build/windows/native"
output = repo / "build/windows/installed-rats-output"
output.mkdir(parents=True, exist_ok=True)

for renderer in ("moonray", "hd_render"):
    found = shutil.which(renderer)
    expected = install / "bin" / (renderer + ".exe")
    if not found or Path(found).resolve() != expected:
        raise RuntimeError(f"Expected installed {expected}, found {found}")
for variable in ("PATH", "PYTHONPATH", "PXR_PLUGINPATH_NAME"):
    for entry in os.environ.get(variable, "").split(os.pathsep):
        if entry and Path(entry).resolve().is_relative_to(native):
            raise RuntimeError(f"Build-tree path remains in {variable}: {entry}")

# Python 3.8+ requires explicit DLL search directories for extension modules.
dll_handles = []
for entry in os.environ["PATH"].split(os.pathsep):
    if entry:
        try:
            dll_handles.append(os.add_dll_directory(entry))
        except OSError:
            pass
from OpenImageIO import ImageBuf, ImageBufAlgo

env = os.environ.copy()
env["RATS_ASSETS_DIR"] = str(repo / "rats/assets")
env["RATS_MOONRAY_THREADS"] = "4"
env["RATS_HD_RENDERER"] = "Moonray (debug)"
cases = [(scene, mode)
         for scene in ("moonray/geometry/sphere", "moonray/geometry/vdbgeometry",
                       "moonray/render_output/basic", "moonray/deep/cornell_box",
                       "moonray/displayfilter/basic/op", "moonray/displayfilter/basic/ramp")
         for mode in ("scalar", "vector")]
cases.append(("moonray/material/glitter/bind_flake_size", "vector"))
cases.append(("hd_render/geometry/skel", "default"))
results = []
for scene, mode in cases:
    command_file = native / "rats/tests" / scene / mode / "render-command.json"
    command = json.loads(command_file.read_text())
    command[0] = sys.executable
    case_output = Path(tempfile.mkdtemp(prefix=f"{scene.replace('/', '-')}-{mode}-", dir=output))
    with (case_output / "render.log").open("w") as log:
        subprocess.run(command, cwd=case_output, env=env, stdout=log,
                       stderr=subprocess.STDOUT, timeout=300, check=True)
    images = sorted(case_output.glob("*.exr"))
    if not images:
        raise RuntimeError(f"No EXR output for {scene} ({mode})")
    parts = []
    for path in images:
        image = ImageBuf(str(path))
        subimages = image.nsubimages
        if subimages < 1:
            raise RuntimeError(f"No readable image parts in {path}: {image.geterror()}")
        for subimage in range(subimages):
            image = ImageBuf(str(path), subimage, 0)
            if not image.read():
                raise RuntimeError(f"Could not read {path}: {image.geterror()}")
            stats = ImageBufAlgo.computePixelStats(image)
            spec = image.spec()
            for channel, nan, inf in zip(spec.channelnames, stats.nancount, stats.infcount):
                # Deep subpixel masks are arbitrary float bit patterns, not
                # numeric color/alpha/depth samples.
                if spec.deep and channel in ("deepabuf.sp1", "deepabuf.sp2"):
                    continue
                if nan or inf:
                    raise RuntimeError(f"Non-finite pixels in {path}, part {subimage}, channel {channel}")
            if spec.width < 1 or spec.height < 1 or spec.nchannels < 1:
                raise RuntimeError(f"Empty image part in {path}, part {subimage}")
            if scene == "moonray/displayfilter/basic/op" and path.name == "normalize.exr":
                black = lit = 0
                for y in range(spec.y, spec.y + spec.height):
                    for x in range(spec.x, spec.x + spec.width):
                        rgb = image.getpixel(x, y)[:3]
                        length = math.sqrt(sum(value * value for value in rgb))
                        if length == 0:
                            black += 1
                        elif abs(length - 1) <= 0.001:  # Half-float output rounding.
                            lit += 1
                        else:
                            raise RuntimeError(f"Expected unit RGB or black in {path} at {(x, y)}: {rgb}")
                if not black or not lit:
                    raise RuntimeError(f"Missing black or lit normalize samples in {path}")
            if scene == "moonray/displayfilter/basic/ramp" and path.name == "radial_ramp.exr":
                # This upstream scene's midpoint control color is blue. EXR
                # scanlines reverse MoonRay's screen-space Y coordinate.
                center = image.getpixel(spec.x + spec.width // 2,
                                        spec.y + spec.height - 1 - spec.height // 2)
                if center[:3] != (0.0, 0.0, 1.0):
                    raise RuntimeError(f"Unexpected radial ramp center in {path}: {center}")
            parts.append({"image": path.name, "part": subimage,
                          "width": spec.width, "height": spec.height,
                          "channels": list(spec.channelnames)})
    results.append({"scene": scene, "mode": mode, "output": str(case_output), "parts": parts})
    print(f"PASS {scene} ({mode}): {len(parts)} image parts with finite numeric samples", flush=True)
(output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
print(f"All {len(results)} installed render checks passed.")
