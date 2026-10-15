"""Build an editable Solaris ALab scene and export its layer stack for Husk."""
import argparse
from collections import Counter
import json
from pathlib import Path
import time

import hou
from pxr import Usd, UsdGeom, UsdRender, UsdShade, UsdUtils
import moonray_houdini as mr

parser = argparse.ArgumentParser()
parser.add_argument('--scene', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--frame', type=int, default=1004)
parser.add_argument('--width', type=int, default=384)
parser.add_argument('--samples', type=int, default=2)
parser.add_argument('--threads', type=int, default=13)
parser.add_argument('--mode', choices=('vectorized', 'xpu', 'scalar'), default='vectorized')
parser.add_argument('--complexity', choices=('low', 'medium', 'high', 'veryhigh'), default='low')
args = parser.parse_args()
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
started = time.monotonic()
hou.hipFile.clear(suppress_save_prompt=True)
hou.setFps(24)
hou.playbar.setFrameRange(1004, 1057)
hou.playbar.setPlaybackRange(1004, 1057)
hou.setFrame(args.frame)
network = hou.node('/stage')
source = network.createNode('sublayer', 'alab_assets')
source.parm('filepath1').set(args.scene.resolve().as_posix())
source.setComment('Netflix Animation Studios ALab. Base assets and techvars textures; no optional baked fur/cloth.')
source.setDisplayFlag(True)
source.setSelected(True, clear_all_selected=True)
print('Loading the ALab stage', flush=True)
stage = source.stage()
assert stage and not source.errors(), source.errors()
types, prototype_types, shaders = Counter(), Counter(), Counter()
cameras, lights = [], []
for prim in stage.Traverse():
    kind = prim.GetTypeName()
    types[kind] += 1
    if prim.IsA(UsdGeom.Camera):
        cameras.append(str(prim.GetPath()))
    if kind.endswith('Light'):
        lights.append(str(prim.GetPath()))
    if prim.IsA(UsdShade.Shader):
        shaders[str(UsdShade.Shader(prim).GetIdAttr().Get())] += 1
for prototype in stage.GetPrototypes():
    for prim in Usd.PrimRange(prototype):
        prototype_types[prim.GetTypeName()] += 1
        if prim.IsA(UsdShade.Shader):
            shaders[str(UsdShade.Shader(prim).GetIdAttr().Get())] += 1
camera = '/root/camera01/GEO/renderCam_hrc/renderCam_buffer/renderCam_srt/renderCam'
assert camera in cameras, cameras
source_camera = UsdGeom.Camera(stage.GetPrimAtPath(camera))
camera_aspect = (source_camera.GetHorizontalApertureAttr().Get(args.frame) /
                 source_camera.GetVerticalApertureAttr().Get(args.frame))
height = round(args.width / camera_aspect)
assert lights, 'No source lights were loaded'
assert types['Mesh'] + prototype_types['Mesh'] > 100, 'The scene geometry did not load'
print(json.dumps({'loaded_types': types, 'prototype_types': prototype_types,
                  'cameras': len(cameras), 'lights': len(lights), 'shaders': shaders}), flush=True)

rop = mr.create_render_setup()
settings = mr.render_settings_node(rop)
mr._set(settings, 'camera', camera)
mr._set(settings, 'includedPurposes', 'default render')
mr._set(settings, 'materialBindingPurposes', 'full allPurpose')
mr._set(settings, 'instantaneousShutter', True)
mr._set(settings, 'disableMotionBlur', True)
settings.parmTuple('resolution').set((args.width, height))
mr._set(settings, 'moonray:localThreads', args.threads)
mr._set(settings, 'moonray:executionMode', args.mode)
mr._set(settings, 'moonray:sceneVariable:pixel_samples', args.samples)
mr._set(settings, 'moonray:sceneVariable:texture_cache_size', 1024)
mr._set(settings, 'moonray:sceneVariable:texture_file_handles', 256)
product = settings.input(0).input(0)
mr._set(product, 'productName', (out / 'alab.$F4.exr').as_posix())
aovs = settings.input(0)
for name in ('P', 'Wp', 'St'):
    aovs.parm('utility_' + name).set(True)
usd = out / 'alab_moonray.usda'
rop.parm('lopoutput').set(usd.as_posix())
rop.parm('f1').set(args.frame)
rop.parm('f2').set(args.frame)
# Husk defaults to veryhigh, which greatly amplifies subdivision on ALab.
# Low is a polygon preview. Higher subdivision needs a larger memory budget;
# this is a test-scene quality choice, not a renderer-wide default change.
rop.parm('husk_complexity').set(args.complexity)
rop.parm('husk_instantshutter').set(True)
rop.setSelected(True, clear_all_selected=True)
final = mr.use_render_settings(rop)
network.layoutChildren()
hip = out / 'ALab_MoonRay.hip'
hou.hipFile.save(str(hip))
print('Saved the editable Houdini scene; exporting layer stack', flush=True)
# Keep file references and instancing; flatten only the authored layer stack.
# This lets the preparation process exit before Husk loads the large scene.
layer = UsdUtils.FlattenLayerStack(final.stage())
assert layer.Export(str(usd))
render_stage = Usd.Stage.Open(str(usd), load=Usd.Stage.LoadNone)
assert render_stage.GetPrimAtPath('/Render/MoonRay/settings')
report = {'prepared': True, 'asset_name': 'Netflix Animation Studios ALab',
          'copyright': 'Netflix Animation Studios ALab Copyright 2025 Netflix, Inc. All rights reserved.',
          'source': str(args.scene.resolve()), 'hip': str(hip), 'usd': str(usd),
          'package': hou.getenv('MOONRAY_HOUDINI_ROOT'), 'frame': args.frame,
          'resolution': [args.width, height],
          'pixel_samples': args.samples, 'samples_per_pixel': args.samples ** 2,
          'mode': args.mode, 'threads': args.threads, 'camera': camera,
          'batch_complexity': args.complexity, 'motion_blur': False,
          'material_purpose': 'full', 'texture_cache_mb': 1024,
          'loaded_types': dict(types), 'prototype_types': dict(prototype_types),
          'shader_types': dict(shaders), 'cameras': cameras, 'lights': lights,
          'excluded_optional_packages': ['4K textures', 'baked fur and cloth', 'Gaussian splat'],
          'seconds': round(time.monotonic() - started, 2), 'warnings': list(source.warnings())}
(out / 'scene-report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({key: report[key] for key in ('prepared', 'hip', 'usd', 'seconds')}), flush=True)
