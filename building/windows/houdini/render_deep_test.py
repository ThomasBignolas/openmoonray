"""Exercise native deep products alongside flat Cryptomatte, through Husk."""
import argparse
import json
from pathlib import Path
import subprocess
import hou
from pxr import Gf, Sdf, Usd, UsdRender

parser = argparse.ArgumentParser()
parser.add_argument('--scene', type=Path, required=True)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--failure', action='store_true')
parser.add_argument('--dcx', action='store_true')
parser.add_argument('--deep-only', action='store_true')
parser.add_argument('--invalid-var', action='store_true')
parser.add_argument('--adaptive', action='store_true')
args = parser.parse_args()
args.out = args.out.resolve()
args.out.mkdir(parents=True, exist_ok=True)
stage = Usd.Stage.Open(str(args.scene.resolve()))
settings = UsdRender.Settings(stage.GetPrimAtPath('/Render/rendersettings'))
settings.CreateResolutionAttr(Gf.Vec2i(160, 90))
settings.GetPrim().CreateAttribute('moonray:sceneVariable:deep_format', Sdf.ValueTypeNames.Int).Set(1 if args.dcx else 0)
if args.adaptive:
    settings.GetPrim().CreateAttribute('moonray:sceneVariable:sampling_mode', Sdf.ValueTypeNames.Int).Set(1)
product = UsdRender.Product(stage.GetPrimAtPath('/Render/Products/beauty'))
product.CreateProductNameAttr((args.out / 'flat.$F4.exr').as_posix())
deep = UsdRender.Product.Define(stage, '/Render/Products/deep')
deep.CreateProductTypeAttr('deep')
deep.CreateProductNameAttr((args.out / 'deep.$F4.exr').as_posix())
if args.failure:
    (args.out / 'file-instead-of-directory').write_text('Force a native writer failure')
    deep.CreateProductNameAttr((args.out / 'file-instead-of-directory/deep.$F4.exr').as_posix())
paths = []
for name, source, dtype in [('beauty', 'beauty', 'color3f'), ('N', 'N', 'normal3f'), ('P', 'P', 'point3f')]:
    var = UsdRender.Var.Define(stage, '/Render/DeepVars/' + name)
    var.CreateSourceNameAttr(source)
    var.CreateSourceTypeAttr('raw')
    var.CreateDataTypeAttr(dtype)
    var.GetPrim().CreateAttribute('driver:parameters:aov:husk:name', Sdf.ValueTypeNames.String).Set(name)
    paths.append(var.GetPath())
deep.CreateOrderedVarsRel().SetTargets(paths)
if args.invalid_var:
    stage.GetPrimAtPath(paths[0]).CreateAttribute('parameters:moonray:result', Sdf.ValueTypeNames.Token).Set('cryptomatte')
settings.GetProductsRel().SetTargets([deep.GetPath()] if args.deep_only else [product.GetPath(), deep.GetPath()])
scene = args.out / 'deep.usda'
stage.Export(str(scene))
with (args.out / 'render.log').open('w') as log:
    command = [str(Path(hou.getenv('HFS')) / 'bin/husk.exe'), '--renderer', 'HdMoonrayRendererPlugin',
        '--settings', '/Render/rendersettings', '-V', '4', '-f', '1', '-n', '1' if args.failure else '2', str(scene)]
    if args.failure:
        command.insert(1, '--disable-disk-check')
    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=180)
report = {'package': hou.getenv('MOONRAY_HOUDINI_ROOT'), 'scene': str(scene), 'returncode': result.returncode,
          'expected_failure': args.failure or args.invalid_var or args.adaptive, 'format': 'dcx' if args.dcx else 'openexr',
          'deep_only': args.deep_only}
(args.out / 'render-report.json').write_text(json.dumps(report, indent=2))
assert (result.returncode != 0) == report['expected_failure'], report
if args.failure:
    assert 'Houdini deep output:' in (args.out / 'render.log').read_text(), 'Failure must reach the native worker'
if args.invalid_var:
    assert 'Unsupported deep Render Var result' in (args.out / 'render.log').read_text()
if args.adaptive:
    assert 'requires Uniform Sampling' in (args.out / 'render.log').read_text()
if not report['expected_failure']:
    for frame in (1, 2):
        for kind in (('deep',) if args.deep_only else ('flat', 'deep')):
            assert (args.out / f'{kind}.{frame:04}.exr').is_file(), (kind, frame)
print(json.dumps(report), flush=True)
