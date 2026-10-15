"""Validate the relocated runtime with only bundled and Windows system paths."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

bundle = Path(sys.argv[1]).resolve()
system = Path(os.environ["SystemRoot"]).resolve()
repo = Path(__file__).resolve().parents[3]
output = repo / "build/windows/bundle-validation"
output.mkdir(parents=True, exist_ok=True)
if not Path(sys.executable).resolve().is_relative_to(bundle):
    raise RuntimeError("Validation must use the bundled Python")
for variable in ("PATH", "PYTHONPATH", "PXR_PLUGINPATH_NAME", "ARRAS_SESSION_PATH"):
    for entry in os.environ.get(variable, "").split(os.pathsep):
        path = Path(entry).resolve()
        if not path.is_relative_to(bundle) and not path.is_relative_to(system):
            raise RuntimeError(f"External runtime path in {variable}: {path}")

manifest = json.loads((bundle / "manifest.json").read_text())
for item in manifest["files"]:
    path = (bundle / item["path"]).resolve()
    if not path.is_relative_to(bundle):
        raise RuntimeError("Manifest path escapes the bundle")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
            raise RuntimeError(f"Bundle file checksum mismatch: {path}")
print(f"PASS bundle manifest: {len(manifest['files'])} verified files", flush=True)

import scene_rdl2 as rdl
from pxr import Usd, UsdGeom, UsdImagingGL, Plug, Sdr, Sdf
from OpenImageIO import ImageBuf

context = rdl.SceneContext()
context.getSceneVariables().set("image_width", 123)
for suffix, writer, reader in (("rdla", rdl.AsciiWriter, rdl.AsciiReader),
                              ("rdlb", rdl.BinaryWriter, rdl.BinaryReader)):
    path = str(output / f"scene roundtrip.{suffix}")
    writer(context).toFile(path)
    restored = rdl.SceneContext()
    reader(restored).fromFile(path)
    assert restored.getSceneVariables().get("image_width") == 123
stage = Usd.Stage.CreateInMemory()
UsdGeom.Sphere.Define(stage, "/sphere").GetRadiusAttr().Set(2.5)
for suffix in ("usda", "usdc"):
    path = str(output / f"usd roundtrip.{suffix}")
    stage.GetRootLayer().Export(path)
    restored = Usd.Stage.Open(path)
    assert UsdGeom.Sphere(restored.GetPrimAtPath("/sphere")).GetRadiusAttr().Get() == 2.5
plugins = UsdImagingGL.Engine.GetRendererPlugins()
for name in ("HdMoonrayRendererPlugin", "HdMoonrayRendererDebugPlugin", "HdStormRendererPlugin"):
    assert name in plugins, (name, plugins)
shader_registry = Sdr.Registry()
for shader in ("DwaBaseMaterial", "UsdPreviewSurface", "ImageMap"):
    assert shader_registry.GetShaderNodeByIdentifier(shader), shader
rgb_array = shader_registry.GetShaderNodeByIdentifier("DwaBaseMaterial").GetShaderInput("iridescence_colors")
assert rgb_array.IsDynamicArray()
assert rgb_array.GetTypeAsSdfType()[0] == Sdf.ValueTypeNames.Color3fArray
definition = json.loads((bundle / "coredata/DwaBaseMaterial.json").read_text())
expected = definition["scene_classes"]["DwaBaseMaterial"]["attributes"]["iridescence_colors"]["default"]
actual = rgb_array.GetDefaultValue()
assert len(actual) == len(expected)
assert all(math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6)
           for color, reference in zip(actual, expected) for a, b in zip(color, reference))
for plugin in Plug.Registry().GetAllPlugins():
    for value in (plugin.path, plugin.resourcePath):
        if value and not Path(value).resolve().is_relative_to(bundle):
            raise RuntimeError(f"Plugin refers outside the relocated bundle: {plugin.name}: {value}")
print("PASS bundled scene/USD serialization, Hydra discovery and shader parsing", flush=True)

# Check the libraries actually loaded by the combined Python/USD/RDL/OIIO process.
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
kernel.GetCurrentProcess.restype = wintypes.HANDLE
psapi.EnumProcessModules.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE),
                                    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
psapi.EnumProcessModules.restype = wintypes.BOOL
psapi.GetModuleFileNameExW.argtypes = (wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD)
psapi.GetModuleFileNameExW.restype = wintypes.DWORD
modules = (wintypes.HMODULE * 1024)()
needed = wintypes.DWORD()
process = kernel.GetCurrentProcess()
if not psapi.EnumProcessModules(process, modules, ctypes.sizeof(modules), ctypes.byref(needed)):
    raise ctypes.WinError(ctypes.get_last_error())
if needed.value > ctypes.sizeof(modules):
    raise RuntimeError("Module audit buffer is too small")
loaded = []
for module in modules[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
    buffer = ctypes.create_unicode_buffer(32768)
    if not psapi.GetModuleFileNameExW(process, module, buffer, len(buffer)):
        raise ctypes.WinError(ctypes.get_last_error())
    path = Path(buffer.value).resolve()
    if not path.is_relative_to(bundle) and not path.is_relative_to(system):
        raise RuntimeError(f"Loaded a DLL outside the bundle and Windows: {path}")
    loaded.append(str(path))
(output / "loaded-modules.json").write_text(json.dumps(loaded, indent=2) + "\n")
print(f"PASS loaded-library audit: {len(loaded)} modules from the bundle or Windows", flush=True)

for script, arguments in (
        ("test_shader_registry.py", ["--definitions", str(bundle / "coredata"),
                                     "--report", str(output / "shader-registry-results.json"),
                                     "--translator", str(bundle / "bin/hd_usd2rdl.exe")]),
        ("test_installed_renders.py", [str(bundle)]),
        ("test_arras_renders.py", [str(bundle), "--bundle"])):
    with (output / f"{script}.log").open("w") as log:
        subprocess.run([sys.executable, str(Path(__file__).with_name(script))] + arguments,
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    print(f"PASS bundled {script}", flush=True)
direct_renders = json.loads((repo / "build/windows/installed-rats-output/results.json").read_text())
shader_registry = json.loads((output / "shader-registry-results.json").read_text())
(output / "results.json").write_text(json.dumps({"bundle": str(bundle), "manifest_files": len(manifest["files"]),
    "loaded_modules": len(loaded), "direct_render_cases": len(direct_renders), "arras_modes": ["scalar", "vectorized"],
    "arras_output_images": 4, "shader_registry_classes": shader_registry["classes_checked"],
    "shader_registry_attributes": shader_registry["attributes_checked"],
    "trusted_reference_comparison": False}, indent=2) + "\n")
