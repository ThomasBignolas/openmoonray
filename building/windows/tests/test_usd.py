"""Check the installed USD ABI, stage IO, and Hydra plugin discovery."""
import os
from pathlib import Path
import sys

root = Path(sys.argv[1])
handles = [os.add_dll_directory(str(root / path)) for path in [
    "build/deps-extra/bin", "build/deps-extra/lib", "build/deps/x64-windows/bin",
    "build/tools/tbb/bin/intel64/vc14",
]]
from pxr import Usd, UsdGeom, UsdImagingGL

stage = Usd.Stage.CreateInMemory()
UsdGeom.Sphere.Define(stage, "/sphere").GetRadiusAttr().Set(2.5)
for suffix in ("usda", "usdc"):
    path = root / "build/windows" / f"usd-test.{suffix}"
    stage.GetRootLayer().Export(str(path))
    restored = Usd.Stage.Open(str(path))
    sphere = UsdGeom.Sphere(restored.GetPrimAtPath("/sphere"))
    assert sphere.GetRadiusAttr().Get() == 2.5
plugins = UsdImagingGL.Engine.GetRendererPlugins()
assert "HdStormRendererPlugin" in plugins, plugins
print("USD", Usd.GetVersion(), "ASCII/binary stage round-trips passed")
print("Hydra plugins:", plugins)
