"""Verify native Solaris execution controls, HIP persistence, and deep output."""
import argparse
import json
from pathlib import Path
import hou
import moonray_houdini as mr
import moonray_deep

parser = argparse.ArgumentParser()
parser.add_argument('--demo', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
args.out = args.out.resolve()
args.out.mkdir(parents=True, exist_ok=True)
hou.hipFile.load(str(args.demo.resolve()), suppress_save_prompt=True)
hou.clearAllSelected()
rop = mr.create_render_setup()
settings = mr.render_settings_node(rop)
parm = settings.parm(hou.text.encodeParm('moonray:executionMode'))
assert parm and 'xpu' in parm.menuItems(), 'Missing native XPU control'
mr._set(settings, 'moonray:executionMode', 'xpu')
settings.parmTuple('resolution').set((160, 90))
mr._set(settings, 'moonray:sceneVariable:pixel_samples', 3)
assert settings.stage().GetPrimAtPath('/Render/MoonRay/settings').GetAttribute('moonray:executionMode').Get() == 'xpu'
product_node = settings.input(0).input(0)
mr._set(product_node, 'productName', (args.out / 'flat.$F4.exr').as_posix())
hou.clearAllSelected()
rop.setSelected(True)
deep = moonray_deep.create()
deep.parm('filename').set((args.out / 'deep.$F4.exr').as_posix())
for name in ('normals', 'positions', 'uv'):
    deep.parm(name).set(True)
# This demo already contains an older Render Settings prim. Make its intended
# XPU settings explicit for both Solaris previews and consumers of the stage.
config = settings.parent().createNode('configurelayer', 'xpu_view_settings')
config.setInput(0, deep)
config.parm('setrendersettings').set(True)
config.parm('rendersettings').set('/Render/MoonRay/settings')
config.setDisplayFlag(True)
config.moveToGoodPosition()
rop.setInput(0, config)
rop.parm('lopoutput').set((args.out / 'xpu-workflow.usd').as_posix())
rop_path, settings_path = rop.path(), settings.path()
hip = args.out / 'MoonRay_XPU_Demo.hip'
hou.hipFile.save(str(hip))
hou.hipFile.load(str(hip), suppress_save_prompt=True)
settings, rop = hou.node(settings_path), hou.node(rop_path)
assert settings.evalParm(hou.text.encodeParm('moonray:executionMode')) == 'xpu'
assert settings.stage().GetPrimAtPath('/Render/MoonRay/settings').GetAttribute('moonray:executionMode').Get() == 'xpu'
assert rop.input(0).stage().GetMetadata('renderSettingsPrimPath') == '/Render/MoonRay/settings'
rop.render(frame_range=(1, 1))
assert not rop.errors(), rop.errors()
assert all((args.out / name).is_file() for name in ('flat.0001.exr', 'deep.0001.exr'))
report = {'passed': True, 'package': hou.getenv('MOONRAY_HOUDINI_ROOT'), 'hip': str(hip),
          'settings_node': settings_path, 'execution_mode': 'xpu', 'hip_reloaded': True,
          'default_render_settings': '/Render/MoonRay/settings',
          'rendered_flat_and_deep': True}
(args.out / 'workflow-validation.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report), flush=True)
