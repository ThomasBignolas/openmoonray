"""Check settings migration, viewport selection and a bounded local CPU render."""
import argparse
import json
from pathlib import Path

import hou
from pxr import UsdRender
import moonray_houdini as mr

parser = argparse.ArgumentParser()
parser.add_argument('--demo', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
args.out = args.out.resolve()
args.out.mkdir(parents=True, exist_ok=True)
hou.hipFile.load(str(args.demo.resolve()), suppress_save_prompt=True)

# An existing HIP's MoonRay folder must gain controls without losing animation
# or values authored by the artist, including other renderers' parameters.
old = hou.node('/stage/moonray_settings1')
assert old is not None
samples = old.parm(hou.text.encodeParm('moonray:sceneVariable:pixel_samples'))
print(mr.__file__, samples.containingFolders(), flush=True)
mr._set(old, 'moonray:sceneVariable:pixel_samples', 2)
samples.setKeyframes((hou.Keyframe(2, 0), hou.Keyframe(3, 1 / hou.fps())))
keys = tuple(k.asCode() for k in samples.keyframes())
camera, products = old.evalParm('camera'), old.evalParm('products')
mode = old.evalParm(hou.text.encodeParm('moonray:executionMode'))
old.setSelected(True, clear_all_selected=True)
assert mr.refresh_settings() == [old]
samples = old.parm(hou.text.encodeParm('moonray:sceneVariable:pixel_samples'))
assert old.parm(hou.text.encodeParm('moonray:localThreads')) is not None
assert tuple(k.asCode() for k in samples.keyframes()) == keys, (keys, tuple(k.asCode() for k in samples.keyframes()))
assert (old.evalParm('camera'), old.evalParm('products')) == (camera, products)
assert old.evalParm(hou.text.encodeParm('moonray:executionMode')) == mode
print('Existing settings and animation preserved', flush=True)

hou.clearAllSelected()
rop = mr.create_render_setup()
settings = mr.render_settings_node(rop)
assert settings.evalParm(hou.text.encodeParm('moonray:localThreads')) == 4
source = rop.input(0)
target = rop.evalParm('rendersettings')
assert source.stage().GetMetadata('renderSettingsPrimPath') == target
count = len(source.parent().children())
assert mr.use_render_settings(rop) == source
assert len(source.parent().children()) == count, 'Repeated activation inserted another node'
rop.parm('rendersettings').set('/missing/render/settings')
try:
    mr.use_render_settings(rop)
except hou.OperationFailed:
    pass
else:
    raise AssertionError('Missing settings were accepted')
assert len(source.parent().children()) == count
rop.parm('rendersettings').set(target)

settings.parmTuple('resolution').set((160, 90))
mr._set(settings, 'moonray:executionMode', 'vectorized')
mr._set(settings, 'moonray:localThreads', 2)
mr._set(settings, 'moonray:sceneVariable:pixel_samples', 2)
stage = rop.input(0).stage()
assert stage.GetPrimAtPath(target).GetAttribute('moonray:localThreads').Get() == 2
assert UsdRender.Settings(stage.GetPrimAtPath(target)).GetProductsRel().GetTargets()
rop.parm('lopoutput').set((args.out / 'reliability.usd').as_posix())
rop.parm('outputimage').set((args.out / 'reliability.exr').as_posix())
hip = args.out / 'MoonRay_Reliability_Demo.hip'
rop_path = rop.path()
hou.hipFile.save(str(hip))
hou.hipFile.load(str(hip), suppress_save_prompt=True)
rop = hou.node(rop_path)
assert rop.input(0).stage().GetMetadata('renderSettingsPrimPath') == target
print('Rendering with two local CPU threads', flush=True)
rop.render(frame_range=(1, 1))
assert not rop.errors(), rop.errors()
assert (args.out / 'reliability.exr').stat().st_size > 10000
report = {'passed': True, 'package': hou.getenv('MOONRAY_HOUDINI_ROOT'),
          'settings_refresh_preserves_animation': True,
          'viewport_matches_rop_settings': True, 'activation_is_idempotent': True,
          'missing_settings_rejected': True, 'hip_reload': True,
          'rendered': True, 'requested_cpu_threads': 2, 'hip': str(hip)}
(args.out / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report), flush=True)
