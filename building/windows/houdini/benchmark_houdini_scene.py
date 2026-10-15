"""Export an existing HIP without changing it and time the actual Hydra worker.

Run under run_bounded.py. This measures headless Hydra, not GUI pixel display.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

import hou
from pxr import UsdUtils
import moonray_houdini as mr

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--hip', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--rop', default='/stage/RENDER_MOONRAY')
parser.add_argument('--frame', type=int, default=1004)
parser.add_argument('--texture-cache-mb', type=int)
parser.add_argument('--texture-handles', type=int)
parser.add_argument('--first-image-only', action='store_true', help='Stop this test after the first image arrives')
args = parser.parse_args()
out = args.out.resolve()
out.mkdir(parents=True, exist_ok=True)
started = time.monotonic()
hou.hipFile.load(str(args.hip.resolve()), suppress_save_prompt=True)
hou.setFrame(args.frame)
rop = hou.node(args.rop)
assert rop and rop.type().name() == 'usdrender_rop', args.rop
settings = mr.render_settings_node(rop)
if args.texture_cache_mb is not None:
    mr._set(settings, 'moonray:sceneVariable:texture_cache_size', args.texture_cache_mb)
if args.texture_handles is not None:
    mr._set(settings, 'moonray:sceneVariable:texture_file_handles', args.texture_handles)
usd = out / 'scene.usdc'
assert UsdUtils.FlattenLayerStack(rop.input(0).stage()).Export(str(usd))
exported = time.monotonic()
report = dict(hip=str(args.hip.resolve()), frame=args.frame, mode='headless Hydra',
              load_and_export_seconds=round(exported-started, 3),
              texture_cache_mb=settings.evalParm(hou.text.encodeParm('moonray:sceneVariable:texture_cache_size')),
              texture_handles=settings.evalParm(hou.text.encodeParm('moonray:sceneVariable:texture_file_handles')),
              package=hou.getenv('MOONRAY_HOUDINI_ROOT'), passed=False)
command = [str(Path(hou.getenv('HFS'))/'bin/husk.exe'), '--renderer', 'HdMoonrayRendererPlugin',
           '--settings', rop.evalParm('rendersettings'), '--frame', str(args.frame),
           '--complexity', 'high', '--disable-motionblur', '--output', str(out/'beauty.exr'), str(usd)]
report['command'] = command
(out/'timing.json').write_text(json.dumps(report, indent=2)+'\n')
render_started = time.monotonic()
first_observed = None
stopped_at_first_image = False
hydra_position = 0
with (out/'render.log').open('w') as log:
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                               env=dict(os.environ, HDM_LOG_FILE=str(out/'hydra.log')))
    while process.poll() is None:
        if first_observed is None and (out/'hydra.log').exists():
            with (out/'hydra.log').open(errors='replace') as trace:
                trace.seek(hydra_position)
                new_text = trace.read()
                hydra_position = trace.tell()
            if 'First MoonRay image received after scene send:' in new_text:
                first_observed = time.monotonic() - render_started
                if args.first_image_only:
                    stopped_at_first_image = True
                    process.terminate()
        if time.monotonic() - render_started > 360:
            report['timed_out'] = True
            process.kill()
        time.sleep(.1)
    returncode = process.wait()
text = (out/'render.log').read_text(errors='replace')
render_errors = [line for line in text.splitlines() if 'Error:' in line or 'Fatal:' in line]
hydra = (out/'hydra.log').read_text(errors='replace') if (out/'hydra.log').exists() else ''
first = re.search(r'First MoonRay image received after scene send: ([0-9.e+-]+) seconds', hydra)
prep = re.search(r'(?:Total render prep|Render prep time)\s*=\s*([0-9:.]+)', text)
report.update(returncode=returncode, total_seconds=round(time.monotonic()-started, 3),
              render_error_count=len(render_errors), render_errors=render_errors[:10],
              first_image_after_husk_start_seconds=round(first_observed, 3) if first_observed is not None else None,
              stopped_at_first_image=stopped_at_first_image,
              first_image_after_scene_send_seconds=float(first[1]) if first else None,
              render_prep=prep[1] if prep else None,
              gpu_fallback='falling back to CPU' in text,
              output_exists=(out/'beauty.exr').is_file(),
              passed=not render_errors and first is not None and
                     (stopped_at_first_image or (returncode == 0 and (out/'beauty.exr').is_file())))
(out/'timing.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2), flush=True)
raise SystemExit(0 if report['passed'] else 1)
