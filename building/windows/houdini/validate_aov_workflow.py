"""Exercise AOV node controls, product links, HIP reload and a real USD Render ROP."""
import argparse
import json
from pathlib import Path
import hou
from pxr import UsdRender
import moonray_houdini as mr
import moonray_aovs

parser = argparse.ArgumentParser()
parser.add_argument('--demo', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
hou.hipFile.load(str(args.demo.resolve()), suppress_save_prompt=True)
hou.clearAllSelected()
rop = mr.create_render_setup()
settings = mr.render_settings_node(rop)
aovs = settings.input(0)
assert aovs.type().name() == 'moonray::aovs::1.0'
assert not aovs.errors(), aovs.errors()

def current():
    stage = settings.stage()
    assert stage and not settings.errors(), settings.errors()
    product = UsdRender.Product(stage.GetPrimAtPath('/Render/MoonRay/beauty'))
    return stage, product.GetOrderedVarsRel().GetTargets()

stage, initial = current()
assert len(initial) == 4, initial
aovs.parm('crypto').set(False)
assert len(current()[1]) == 3
aovs.parm('crypto').set(True)
aovs.parm('cryptoname').set('HeroCrypto')
aovs.parm('depth').set(3)
stage, paths = current()
assert str(paths[-1]) == '/Render/MoonRay/AOVs/HeroCrypto'
assert stage.GetPrimAtPath(paths[-1]).GetAttribute('parameters:moonray:cryptomatte_depth').Get() == 3
aovs.parm('cryptoname').set('Cryptomatte')
for key in ('P', 'Wp', 'St', 'motionvec'):
    aovs.parm('utility_' + key).set(True)
aovs.parm('all_light').set(True)
stage, paths = current()
assert len(paths) == 9, paths
settings.parmTuple('resolution').set((160, 90))
mr._set(settings, 'moonray:sceneVariable:pixel_samples', 3)
rop.parm('lopoutput').set((args.out.resolve() / 'aov-workflow.usd').as_posix())
rop.parm('outputimage').set((args.out.resolve() / 'aov-workflow.exr').as_posix())
hip = args.out.resolve() / 'MoonRay_AOV_Demo.hip'
hou.hipFile.save(str(hip))
rop_path, aov_path = rop.path(), aovs.path()
hou.hipFile.load(str(hip), suppress_save_prompt=True)
rop, aovs = hou.node(rop_path), hou.node(aov_path)
assert aovs.evalParm('crypto_normals') and aovs.evalParm('crypto_uv')
rop.render()
assert not rop.errors(), rop.errors()
report = {'package': hou.getenv('MOONRAY_HOUDINI_ROOT'), 'hip': str(hip),
          'aov_node': aov_path, 'render_node': rop_path, 'var_count': len(paths),
          'enable_disable': True, 'custom_name': True, 'depth_update': True,
          'hip_reload': True, 'rendered': True, 'errors': list(rop.errors())}
(args.out / 'workflow-validation.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2), flush=True)
