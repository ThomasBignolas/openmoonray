"""Check native HDA ramp translation, including mixed interpolation modes."""
import json
from pathlib import Path
import sys
import hou

directory = Path(sys.argv[1]).resolve()
hou.hipFile.load(str(directory / 'MoonRay_Solaris_Demo.hip'), suppress_save_prompt=True)
node = hou.node('/stage/moonray_materials/ceramic')
node.parm('iridescence_ramp').set(hou.Ramp(
    (hou.rampBasis.Constant, hou.rampBasis.Linear, hou.rampBasis.Hermite),
    (0, 0.5, 1), ((1, 0, 0), (0, 1, 0), (0, 0, 1))))
stage = hou.node('/stage/moonray_settings').stage()
shader = stage.GetPrimAtPath('/Looks/ceramic/ceramic')
attribute = shader.GetAttribute('inputs:iridescence_interpolations')
assert str(attribute.GetTypeName()) == 'int[]'
assert list(attribute.Get()) == [0, 1, 4]
assert len(shader.GetAttribute('inputs:iridescence_colors').Get()) == 3
assert list(shader.GetAttribute('inputs:iridescence_positions').Get()) == [0, 0.5, 1]
result = {'houdini': hou.applicationVersionString(), 'mixed_ramp_interpolation': list(attribute.Get()),
          'usd_type': str(attribute.GetTypeName()), 'saved_scene_modified': False}
(directory / 'material-validation.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
