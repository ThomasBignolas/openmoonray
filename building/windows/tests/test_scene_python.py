"""Exercise the compiled extension, scene objects, and both serialization formats."""
import os
from pathlib import Path
import sys

dll_handles = [os.add_dll_directory(path) for path in os.environ["OMR_DLL_DIRS"].split(";")]
import scene_rdl2 as rdl

output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
context = rdl.SceneContext()
variables = context.getSceneVariables()
variables.set("image_width", 123)
variables.set("image_height", 45)
assert variables.get("image_width") == 123
assert variables.get("image_height") == 45
for suffix, writer, reader in [
    ("rdla", rdl.AsciiWriter, rdl.AsciiReader),
    ("rdlb", rdl.BinaryWriter, rdl.BinaryReader),
]:
    path = str(output / f"scene with spaces.{suffix}")
    writer(context).toFile(path)
    restored = rdl.SceneContext()
    reader(restored).fromFile(path)
    assert restored.getSceneVariables().get("image_width") == 123
    assert restored.getSceneVariables().get("image_height") == 45
print("Native Python scene creation and ASCII/binary round-trips passed")
