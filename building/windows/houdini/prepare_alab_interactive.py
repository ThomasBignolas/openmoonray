"""Save a separate ALab XPU scene with inexpensive startup and preview settings."""
import argparse
import json
import os
from pathlib import Path
import time

import hou
from pxr import Usd, UsdRender, UsdUtils
import moonray_houdini as mr

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--hip', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
destination = out / 'ALab_MoonRay_XPU.hip'
if destination.exists():
    raise RuntimeError('Use a new output directory; preserve existing scene edits.')
started = time.monotonic()
hou.setUpdateMode(hou.updateMode.Manual)
hou.hipFile.load(str(args.hip.resolve()), suppress_save_prompt=True)
hou.setFrame(1004)
hou.setUpdateMode(hou.updateMode.AutoUpdate)
network = hou.node('/stage')
source = network.node('alab_assets')
original_source = source.evalParm('filepath1')
print('Composing original ALab assets', flush=True)
stage = source.stage()
assert stage and not source.errors(), source.errors()
composition_seconds = time.monotonic() - started

# Collapse the small entry layer stack into a binary crate. Keep asset
# references, geometry payloads, animation and instancing intact.
cached = out / 'alab_entry.usdc'
assert UsdUtils.FlattenLayerStack(stage).Export(str(cached))
del stage
source.parm('filepath1').set(cached.as_posix())
source.setComment('ALab entry cache: binary USD, retaining asset references and instances.\n'
                  'Original: ' + original_source + '\nExisting mipmapped textures are reused.')
rop = network.node('RENDER_MOONRAY')
assert rop
settings = mr.render_settings_node(rop)
settings.setSelected(True, clear_all_selected=True)
mr.refresh_settings()
threads = min(8, max(1, (os.cpu_count() or 2) - 1))
mr._set(settings, 'moonray:executionMode', 'xpu')
mr._set(settings, 'moonray:localThreads', threads)
mr._set(settings, 'moonray:forcePolygon', True)
mr._set(settings, 'moonray:info', True)
mr._set(settings, 'moonray:sceneVariable:pixel_samples', 3)
mr._set(settings, 'moonray:sceneVariable:texture_cache_size', 512)
mr._set(settings, 'moonray:sceneVariable:texture_file_handles', 256)
mr._set(settings, 'disableMotionBlur', True)
mr._set(settings, 'instantaneousShutter', True)
settings.parmTuple('resolution').set((384, 256))
settings.setComment('XPU preview: CPU + NVIDIA GPU, %d CPU threads, 384 x 256, 9 samples/pixel.\n'
                    'ALab assets, materials and lights. Polygon control cages; motion blur off.\n'
                    'Disable Polygon Preview for final subdivision surfaces.' % threads)
settings.setGenericFlag(hou.nodeFlag.DisplayComment, True)
rop.parm('husk_complexity').set('low')
rop.parm('husk_instantshutter').set(True)
rop.parm('lopoutput').set((out / 'render/alab_xpu.usd').as_posix())
product = next(n for n in rop.inputAncestors() if n.type().name() == 'renderproduct')
mr._set(product, 'productName', (out / 'render/alab_xpu.$F4.exr').as_posix())
aovs = next((n for n in rop.inputAncestors() if n.type().name() == 'moonray::aovs::1.0'), None)
if aovs:
    aovs.bypass(True)
    aovs.setComment('Extra AOVs are bypassed for this interactive preview. Unbypass for Cryptomatte and utility outputs.')
rop.setComment('XPU disk render. For interactive rendering use MoonRay > Start / Resume Live Render.\n'
               'The scene opens in the regular viewport to avoid starting a large render on load.')
final = mr.use_render_settings(rop)
settings.setSelected(True, clear_all_selected=True)
final.setDisplayFlag(True)
network.layoutChildren()
hou.setUpdateMode(hou.updateMode.AutoUpdate)
hou.hipFile.save(str(destination))
prepared = final.stage()
rs = prepared.GetPrimAtPath('/Render/MoonRay/settings')
checks = {
    'xpu': rs.GetAttribute('moonray:executionMode').Get() == 'xpu',
    'threads_reserved': rs.GetAttribute('moonray:localThreads').Get() < os.cpu_count(),
    'polygon_preview_authored': rs.GetAttribute('moonray:forcePolygon').Get() is True,
    'prep_statistics_authored': rs.GetAttribute('moonray:info').Get() is True,
    'camera_present': bool(prepared.GetPrimAtPath(UsdRender.Settings(rs).GetCameraRel().GetTargets()[0])),
    'binary_entry': cached.read_bytes()[:8] == b'PXR-USDC',
    'instances_retained': len(prepared.GetPrototypes()) > 100,
    'no_color_rebuild_on_load': not any(n.type().name() == 'moonray::color::1.0' for n in rop.inputAncestors()),
    'stage_valid': not final.errors(),
}
assert all(checks.values()), checks
report = {'prepared': True, 'hip': str(destination), 'original_hip': str(args.hip.resolve()),
          'asset_entry': original_source, 'cached_entry': str(cached), 'checks': checks,
          'package': hou.getenv('MOONRAY_HOUDINI_ROOT'), 'threads': threads,
          'resolution': [384,256], 'samples_per_pixel': 9, 'extra_aovs': False,
          'color': 'Original ALab shader interpretation; existing mipmapped assets reused. No new color conversion.',
          'startup_renderer': 'Houdini VK', 'render_started': False,
          'original_composition_seconds': round(composition_seconds,2),
          'seconds': round(time.monotonic()-started,2)}
(out / 'scene-report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2),flush=True)
