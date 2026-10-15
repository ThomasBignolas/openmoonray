"""Exercise installed native Arras rendering and an interactive scene update.

Uses the upstream RATS skinned-geometry scene; this is not a canonical comparison.
Dot-source Enter-MoonRayEnvironment.ps1 -InstallPrefix before invoking it.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("install", type=Path)
parser.add_argument("--bundle", action="store_true", help="Use the Arras worker bundled with the renderer")
parser.add_argument("--remote-url", help="Coordinator base URL, without /coordinator/1/sessions")
parser.add_argument("--session-directory", type=Path, help="Session definitions for the remote worker platform")
parser.add_argument("--hosts", type=int, default=1, help="Number of remote render computations")
parser.add_argument("--output", type=Path, help="Isolated render evidence directory")
parser.add_argument("--timeout", type=int, default=120, help="Seconds allowed for each render and update")
args = parser.parse_args()
if args.session_directory and not args.remote_url:
    parser.error("--session-directory requires --remote-url")
install = args.install.resolve()
repo = Path(__file__).resolve().parents[3]
native = repo / "build/windows/native"
output = args.output or repo / ("build/windows/remote-arras-output" if args.remote_url else
                               "build/windows/installed-arras-output")
output = output.resolve()
output.mkdir(parents=True, exist_ok=True)
programs = [("hd_render", install / "bin/hd_render.exe")]
if not args.remote_url:
    programs.append(("execComp", install / "bin/execComp.exe" if args.bundle else
                     repo / "build/deps-arras/bin/execComp.exe"))
for program, expected in programs:
    found = shutil.which(program)
    if not found or Path(found).resolve() != expected:
        raise RuntimeError(f"Expected {expected}, found {found}")
for variable in ("PATH", "PYTHONPATH", "PXR_PLUGINPATH_NAME", "ARRAS_SESSION_PATH"):
    for entry in os.environ.get(variable, "").split(os.pathsep):
        if entry and Path(entry).resolve().is_relative_to(native):
            raise RuntimeError(f"Build-tree path remains in {variable}: {entry}")

dll_handles = []
for entry in os.environ["PATH"].split(os.pathsep):
    if entry:
        try:
            dll_handles.append(os.add_dll_directory(entry))
        except OSError:
            pass
from OpenImageIO import ImageBuf, ImageBufAlgo

env = os.environ.copy()
for variable, directory in (("TMP", "at"), ("TEMP", "at"), ("HOME", "arras-test-home")):
    path = repo / "build" / directory
    path.mkdir(exist_ok=True)
    env[variable] = str(path)
env.update(RATS_ASSETS_DIR=str(repo / "rats/assets"), RATS_HD_RENDERER="Moonray",
           HDMOONRAY_LOCAL_RESERVED_CORES=str(max(0, (os.cpu_count() or 1) - 4)),
           HDMOONRAY_LOGLEVEL="4", DWA_CONFIG_SERVICE="")
if args.remote_url:
    env.update(HDMOONRAY_HOSTS=str(args.hosts), HDMOONRAY_STACK="url-" + args.remote_url.rstrip("/"),
               HDMOONRAY_MAX_CONNECT_RETRIES="0")
    if args.session_directory:
        session_directory = args.session_directory.resolve(strict=True)
        for name in ("hd_single.sessiondef", "hd_multi.sessiondef"):
            if not (session_directory / name).is_file():
                raise RuntimeError(f"Missing remote session definition: {session_directory / name}")
        env["ARRAS_SESSION_PATH"] = str(session_directory)
else:
    env["HDMOONRAY_HOSTS"] = "0"
base_command = json.loads((native / "rats/tests/hd_render/geometry/skel/default/render-command.json").read_text())
base_command[0] = sys.executable
results = []
for mode in ("scalar", "vectorized"):
    case = Path(tempfile.mkdtemp(prefix=f"{mode}-", dir=output))
    delta = case / "rotate.usda"
    delta.write_text('#usda 1.0\nover "group1" {\n    float xformOp:rotateX = -45\n}\n')
    command = base_command + ["-set", "executionMode", mode,
                              "-delta_in", str(delta), "-delta_out", "delta.exr"]
    with (case / "render.log").open("w") as log:
        process = subprocess.Popen(command, cwd=case, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            # This PID is the wrapper we just started; stop only its process tree.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            process.wait()
            raise RuntimeError(f"Arras render timed out; see {case / 'render.log'}")
        if code:
            raise RuntimeError(f"Arras render exited {code}; see {case / 'render.log'}")
    log_text = (case / "render.log").read_text(errors="replace")
    if "ProgressiveFrame" not in log_text:
        raise RuntimeError("No evidence of frames from the real MoonRay computation")
    if args.remote_url:
        session_ids = re.findall(r'Http Response \(200\):[^\n]*"sessionId"\s*:\s*"([^"\s]+)"', log_text)
        if not session_ids or "Connecting via host:port" not in log_text:
            raise RuntimeError("Remote Arras session creation and TCP connection were not recorded")
        if "Spawning: execComp" in log_text:
            raise RuntimeError("Remote test unexpectedly launched a local computation")
    elif "computation_progmcrt.dll" not in log_text:
        raise RuntimeError("No evidence of the native MoonRay computation DLL")
    images, parts = [], []
    for filename in ("scene.exr", "delta.exr"):
        image = ImageBuf(str(case / filename))
        if not image.read():
            raise RuntimeError(image.geterror())
        spec = image.spec()
        stats = ImageBufAlgo.computePixelStats(image)
        if (spec.width, spec.height, spec.nchannels) != (256, 192, 4):
            raise RuntimeError(f"Unexpected image dimensions/channels: {filename}")
        if any(stats.nancount) or any(stats.infcount) or max(stats.max[:3]) <= 0:
            raise RuntimeError(f"Empty or non-finite render: {filename}")
        images.append(image)
        parts.append({"image": filename, "width": spec.width, "height": spec.height,
                      "channels": list(spec.channelnames), "average": list(stats.avg)})
    max_change = max(abs(a - b) for y in range(192) for x in range(256)
                     for a, b in zip(images[0].getpixel(x, y), images[1].getpixel(x, y)))
    if max_change < 0.1:
        raise RuntimeError("The geometry rotation did not change the rendered image")
    results.append({"mode": mode, "output": str(case), "parts": parts, "delta_max_change": max_change,
                    "coordinator_url": args.remote_url,
                    "remote_session_ids": session_ids if args.remote_url else []})
    location = "remote" if args.remote_url else "installed"
    print(f"PASS {location} Arras {mode}: initial render and geometry update, finite RGBA pixels", flush=True)
(output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
