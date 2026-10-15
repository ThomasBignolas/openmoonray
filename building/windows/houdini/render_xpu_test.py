"""Render matched CPU/GPU frames with Husk; reject silent CPU fallback."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

import hou
from pxr import Gf, Sdf, Usd, UsdRender

parser = argparse.ArgumentParser()
parser.add_argument('--scene', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--settings', default='/Render/rendersettings')
parser.add_argument('--modes', nargs='+', default=['vectorized', 'xpu'])
parser.add_argument('--frames', type=int, default=2)
parser.add_argument('--samples', type=int, default=3)
parser.add_argument('--width', type=int, default=160)
parser.add_argument('--expect-fallback', action='store_true')
args = parser.parse_args()
args.out = args.out.resolve()
args.out.mkdir(parents=True, exist_ok=True)
report = {'package': hou.getenv('MOONRAY_HOUDINI_ROOT'), 'source': str(args.scene.resolve()), 'renders': []}
for mode in args.modes:
    stage = Usd.Stage.Open(str(args.scene.resolve()))
    settings = UsdRender.Settings(stage.GetPrimAtPath(args.settings))
    assert settings, args.settings
    settings.CreateResolutionAttr(Gf.Vec2i(args.width, round(args.width * 9 / 16)))
    prim = settings.GetPrim()
    prim.CreateAttribute('moonray:executionMode', Sdf.ValueTypeNames.String).Set(mode)
    prim.CreateAttribute('moonray:sceneVariable:pixel_samples', Sdf.ValueTypeNames.Int).Set(args.samples)
    if not args.expect_fallback:
        for var in stage.Traverse():
            if var.IsA(UsdRender.Var):
                for name in ('record_reflected', 'record_refracted'):
                    attr = var.GetAttribute('parameters:moonray:cryptomatte_' + name)
                    if attr:
                        attr.Set(False)
    files = []
    for i, path in enumerate(settings.GetProductsRel().GetTargets()):
        product = UsdRender.Product(stage.GetPrimAtPath(path))
        filename = f'{mode}-{i}.$F4.exr'
        product.CreateProductNameAttr((args.out / filename).as_posix())
        files.append(filename)
    scene = args.out / f'{mode}.usda'
    stage.Export(str(scene))
    log_path = args.out / f'{mode}.log'
    env = os.environ.copy()
    # Verify the authored USD setting wins over a different viewport default.
    env['HDMOONRAY_EXEC_MODE'] = 'auto'
    env['HDMOONRAY_INFO'] = '1'
    start = time.monotonic()
    with log_path.open('w') as log:
        process = subprocess.run([str(Path(hou.getenv('HFS')) / 'bin/husk.exe'),
            '--renderer', 'HdMoonrayRendererPlugin', '--settings', args.settings,
            '-V', '4', '-f', '1', '-n', str(args.frames), str(scene)],
            env=env, stdout=log, stderr=subprocess.STDOUT, timeout=300)
    text = re.sub(r'\x1b\[[0-9;]*m', '', log_path.read_text(errors='replace'))
    record = {'mode': mode, 'returncode': process.returncode, 'seconds': time.monotonic() - start,
              'files': files, 'gpu_evidence': [line for line in text.splitlines()
                  if any(word in line for word in ('GPU:', 'GPU ', 'XPU rendering', 'Executing ', 'XPU requested'))]}
    report['renders'].append(record)
    (args.out / 'render-report.json').write_text(json.dumps(report, indent=2) + '\n')
    assert process.returncode == 0, record
    for filename in files:
        for frame in range(1, args.frames + 1):
            assert (args.out / filename.replace('$F4', f'{frame:04}')).is_file(), filename
    if mode == 'xpu' and args.expect_fallback:
        assert 'XPU requested; using scalar CPU rendering to preserve:' in text, 'Expected feature fallback'
        assert 'GPU: Creating accelerator' not in text, 'Unsupported features must use scalar CPU'
    elif mode == 'xpu':
        assert 'GPU: Creating accelerator' in text, 'No GPU accelerator startup evidence'
        assert 'falling back' not in text.lower(), 'XPU fell back to CPU; inspect ' + str(log_path)
        assert 'GPU: Allocating rays buffer' in text, 'GPU pipeline did not initialize'
        fractions = re.findall(r'GPU bundled (?:intersection|occlusion) ray utilization\s*=\s*([\d.]+)%', text)
        assert fractions and all(float(v) > 0 for v in fractions), 'No actual GPU ray processing'
    elif mode == 'vectorized':
        assert 'Executing a vectorized render since execution mode was set to vector.' in text
    print(json.dumps({k: v for k, v in record.items() if k != 'gpu_evidence'}), flush=True)
