"""Exercise the deep node, HIP reload and actual USD Render ROP output."""
import argparse
import json
from pathlib import Path
import hou
from pxr import UsdRender
import moonray_houdini as mr
import moonray_deep

parser = argparse.ArgumentParser()
parser.add_argument('--demo', required=True, type=Path)
parser.add_argument('--out', required=True, type=Path)
args = parser.parse_args()
args.out = args.out.resolve()
args.out.mkdir(parents=True, exist_ok=True)
hou.hipFile.load(str(args.demo.resolve()), suppress_save_prompt=True)
hou.clearAllSelected()
rop = mr.create_render_setup()
settings = mr.render_settings_node(rop)
settings.parmTuple('resolution').set((160, 90))
mr._set(settings, 'moonray:sceneVariable:pixel_samples', 3)
hou.clearAllSelected()
rop.setSelected(True)
deep = moonray_deep.create()
color = next(n for n in rop.inputAncestors() if n.type().name() == 'moonray::color::1.0')
assert deep in color.inputAncestors() and deep.input(0) == settings
deep.parm('filename').set((args.out / 'deep.$F4.exr').as_posix())
for name in ('normals', 'positions', 'uv'):
    deep.parm(name).set(True)

def inspect():
    stage = deep.stage()
    assert stage and not deep.errors(), deep.errors()
    render_settings = UsdRender.Settings(stage.GetPrimAtPath('/Render/MoonRay/settings'))
    product = UsdRender.Product(stage.GetPrimAtPath('/Render/MoonRay/deep'))
    return render_settings, product

render_settings, product = inspect()
assert product.GetPath() in render_settings.GetProductsRel().GetTargets()
assert product.GetProductTypeAttr().Get() == 'deep'
assert '$F4' in str(product.GetProductNameAttr().Get())
assert len(product.GetOrderedVarsRel().GetTargets()) == 4
deep.parm('enable').set(False)
assert not inspect()[1]
deep.parm('enable').set(True)
# AOVs downstream must leave deep products alone.
extra = deep.parent().createNode('moonray::aovs::1.0', 'extra_flat_aovs')
extra.setInput(0, deep)
extra.parm('varroot').set('/Render/MoonRay/ExtraAOVs')
stage = extra.stage()
assert stage and not extra.errors(), extra.errors()
assert len(UsdRender.Product(stage.GetPrimAtPath('/Render/MoonRay/deep')).GetOrderedVarsRel().GetTargets()) == 4
extra.destroy()
rop.parm('lopoutput').set((args.out / 'deep-workflow.usd').as_posix())
# Set the flat Product path directly; a ROP output override can also affect native products.
product_node = settings.input(0).input(0)
mr._set(product_node, 'productName', (args.out / 'flat.$F4.exr').as_posix())
hip = args.out / 'MoonRay_Deep_Demo.hip'
hou.hipFile.save(str(hip))
deep_path, rop_path = deep.path(), rop.path()
hou.hipFile.load(str(hip), suppress_save_prompt=True)
deep, rop = hou.node(deep_path), hou.node(rop_path)
assert deep.evalParm('uv') and deep.evalParm('positions')
rop.render(frame_range=(1, 1))
assert not rop.errors(), rop.errors()
assert (args.out / 'deep.0001.exr').is_file()
assert (args.out / 'flat.0001.exr').is_file()
report = {'package': hou.getenv('MOONRAY_HOUDINI_ROOT'), 'hip': str(hip),
          'deep_node': deep_path, 'render_node': rop_path, 'enabled_disabled': True,
          'hip_reloaded': True, 'aov_isolation': True, 'rendered': True}
(args.out / 'workflow-validation.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2), flush=True)
