"""Exercise the shelf's scene creation and rendering with real Houdini nodes."""
import json
from pathlib import Path
import sys
import hou
from pxr import UsdRender

directory = Path(sys.argv[1]).resolve()
hou.hipFile.load(str(directory / 'MoonRay_Solaris_Demo.hip'), suppress_save_prompt=True)
import moonray_houdini as mr

hou.clearAllSelected()
rop = mr.create_render_setup()
settings = mr.render_settings_node(rop)
stage = settings.stage()
assert stage.GetPrimAtPath('/Render/MoonRay/settings')
assert list(UsdRender.Settings(stage.GetPrimAtPath('/Render/MoonRay/settings')).GetProductsRel().GetTargets())
assert len(UsdRender.Product(stage.GetPrimAtPath('/Render/MoonRay/beauty')).GetOrderedVarsRel().GetTargets()) == 4
assert rop.evalParm('renderer') == mr.RENDERER
settings.parmTuple('resolution').set((160, 90))
mr._set(settings, 'moonray:sceneVariable:pixel_samples', 2)
rop.parm('lopoutput').set(str(directory / 'workflow-test.usd'))
rop.parm('outputimage').set(str(directory / 'workflow-test.exr'))
rop.render()
assert not rop.errors(), rop.errors()
assert (directory / 'workflow-test.exr').stat().st_size > 10000

result = {'render_node': rop.path(), 'errors': list(rop.errors()), 'materials': [], 'lights': []}
for shader in ('DwaBaseMaterial', 'DwaRefractiveMaterial', 'DwaSkinMaterial', 'BaseVolume'):
    material = mr.create_material(shader)
    usd = material.parent().stage()
    assert any(p.GetTypeName() == 'Shader' and p.GetAttribute('info:id').Get() == shader for p in usd.Traverse())
    result['materials'].append(shader)
for shape in ('rect', 'disk', 'dome', 'distant'):
    light = mr.create_light(shape)
    assert not light.errors(), light.errors()
    assert light.stage()
    if shape == 'dome':
        assert any(p.GetTypeName() in ('DomeLight', 'DomeLight_1') and
                   p.GetAttribute('moonray:class').Get() == 'EnvLight'
                   for p in light.stage().Traverse())
    result['lights'].append(shape)
assignment = mr.assign_material()
assert assignment.evalParm('primpattern1') == ''
assert assignment in rop.inputAncestors(), 'New lights/materials did not reach the render node'
color = next(n for n in rop.inputAncestors() if n.type().name() == 'moonray::color::1.0')
assert assignment in color.inputAncestors(), 'New scene edits bypass color preparation'
rop.setSelected(True, clear_all_selected=True)
assert mr.show_settings() == settings
assert assignment in settings.parent().displayNode().inputAncestors(), 'Showing settings hid later scene edits'
rop.render()
assert not rop.errors(), rop.errors()
result['assignment_node'] = assignment.path()
result['scene_saved'] = False
(directory / 'workflow-validation.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2), flush=True)
