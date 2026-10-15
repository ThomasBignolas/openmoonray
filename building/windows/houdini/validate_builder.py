"""Validate the builder's terminal wiring, editable shader and a bound render."""
import json
from pathlib import Path
import hou
from pxr import UsdShade
import moonray_houdini as mr

root = Path(hou.getenv('MOONRAY_HOUDINI_ROOT')).parent
hou.hipFile.load(str(root / 'demo/MoonRay_Solaris_Demo.hip'), suppress_save_prompt=True)
library = hou.node('/stage/moonray_materials')
old = library.node('ceramic')
old.setName('ceramic_original')
old.setMaterialFlag(False)
builder = mr._setup_material_builder(library.createNode('subnet', 'ceramic'))
shader = builder.node('surface')
shader.parmTuple('albedo').set((0.08, 0.35, 0.07))
assert shader.parm('roughness') or shader.parm('specular_roughness')
stage = library.stage()
material = UsdShade.Material(stage.GetPrimAtPath('/Looks/ceramic'))
surface = material.GetSurfaceOutput('moonray')
assert surface and surface.HasConnectedSource(), stage.Flatten().ExportToString()
source = surface.GetConnectedSource()[0].GetPrim()
assert source.GetAttribute('info:id').Get() == 'DwaBaseMaterial', source
assert shader.parmTuple('albedo') and len(shader.parms()) > 100
assert builder.isMaterialFlagSet() and not shader.isMaterialFlagSet()
settings = hou.node('/stage/moonray_settings')
settings.parmTuple('resolution').set((320, 180))
mr._set(settings, 'moonray:sceneVariable:pixel_samples', 2)
rop = hou.node('/stage/RENDER_MOONRAY')
rop.parm('outputimage').set(str(root / 'demo/builder-test.exr'))
rop.parm('lopoutput').set(str(root / 'demo/builder-test.usd'))
rop.render()
assert not rop.errors(), rop.errors()
assert (root / 'demo/builder-test.exr').stat().st_size > 10000
result = {'builder': builder.path(), 'shader': str(source.GetPath()),
          'shader_parameters': len(shader.parms()), 'surface_connected': True,
          'render_errors': list(rop.errors()), 'original_hip_saved': False}
(root / 'builder-validation.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2), flush=True)
